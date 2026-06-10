"""
Tests for FactChecker service (PydanticAI).

Tests:
- check_claim_async returns structured response (incl. double_check fields)
- Context is passed to the agent
- Usage limit retry behavior
- Error handling returns "unklar" consistency
- check_claims_async processes multiple claims
- Self-critique annotation
"""

import pytest
from unittest.mock import AsyncMock, patch

from pydantic_ai import models, UsageLimitExceeded
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel, AgentInfo
from pydantic_ai.models.test import TestModel

from backend.services.fact_checker import FactChecker, FactCheckResponse, Source, SelfCritiqueResponse

models.ALLOW_MODEL_REQUESTS = False


class TestFactCheckerCheckClaim:
    """Tests for FactChecker.check_claim_async()."""

    async def test_check_claim_returns_structured_response(self, mock_fact_checker, mock_fact_check_response):
        """check_claim_async returns properly structured response including double_check fields."""
        result = await mock_fact_checker.check_claim_async(
            speaker="Angela Merkel",
            claim="Deutschland hat 80 Millionen Einwohner."
        )

        assert isinstance(result, dict)
        assert result["speaker"] == "Test Speaker"
        assert result["original_claim"] == "Test claim statement"
        assert result["consistency"] == "hoch"
        assert "verifizierte" in result["evidence"].lower() or "quellen" in result["evidence"].lower()
        assert isinstance(result["sources"], list)
        assert len(result["sources"]) == 2
        assert result["double_check"] is False
        assert result["critique_note"] == ""

    async def test_check_claim_passes_context_to_agent(self, mock_fact_checker, mock_fact_check_response):
        """check_claim_async passes the context into the prompt the agent receives."""
        captured = {}

        def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            # First user prompt is the claim JSON; capture its content.
            captured["prompt"] = messages[0].parts[-1].content
            return ModelResponse(parts=[TextPart(mock_fact_check_response.model_dump_json())])

        with mock_fact_checker.agent.override(model=FunctionModel(capture)):
            try:
                await mock_fact_checker.check_claim_async(
                    speaker="Test Speaker", claim="Test claim", context="Maischberger, 15.01.2024"
                )
            except Exception:
                pass  # output coercion path is not under test here
        assert "Maischberger" in captured["prompt"]

    async def test_usage_limit_retries_once_then_succeeds(self, mock_fact_check_response, monkeypatch):
        """On UsageLimitExceeded, retries once and returns a successful result."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "k", "TAVILY_API_KEY": "k"}):
            checker = FactChecker()

        ok_model = TestModel(call_tools=[], custom_output_args=mock_fact_check_response.model_dump())
        calls = {"n": 0}
        real_run = checker.agent.run

        async def flaky_run(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise UsageLimitExceeded("limit")
            return await real_run(*args, **kwargs)

        with checker.agent.override(model=ok_model), \
             patch.object(checker, "critique_agent", None):
            monkeypatch.setattr(checker.agent, "run", flaky_run)
            result = await checker.check_claim_async("Speaker", "Claim")

        assert calls["n"] == 2
        assert result["consistency"] == "hoch"

    async def test_check_claim_handles_error_gracefully(self, mock_fact_check_response, monkeypatch):
        """check_claim_async returns 'unklar' when the agent run raises."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key", "TAVILY_API_KEY": "test-tavily-key"}):
            checker = FactChecker()

        async def boom(*args, **kwargs):
            raise Exception("Search API failed")

        with patch.object(checker, "critique_agent", None):
            monkeypatch.setattr(checker.agent, "run", boom)
            result = await checker.check_claim_async(
                speaker="Test Speaker",
                claim="Some claim to verify"
            )

        assert result["consistency"] == "unklar"
        assert result["speaker"] == "Test Speaker"
        assert result["original_claim"] == "Some claim to verify"
        assert "Fehler" in result["evidence"]
        assert result["sources"] == []

    async def test_check_claim_uses_configured_model(self):
        """check_claim_async uses model from environment."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
            "GEMINI_MODEL_FACT_CHECKER": "gemini-custom-model",
        }):
            checker = FactChecker()

            assert checker.model_name == "gemini-custom-model"


class TestFactCheckerCheckClaims:
    """Tests for FactChecker.check_claims_async()."""

    async def test_check_claims_async_processes_list(self, mock_fact_checker):
        """check_claims_async processes multiple claims sequentially."""
        claims = [
            {"name": "Speaker A", "claim": "Claim 1"},
            {"name": "Speaker B", "claim": "Claim 2"},
            {"name": "Speaker C", "claim": "Claim 3"},
        ]

        results = await mock_fact_checker.check_claims_async(claims)

        assert isinstance(results, list)
        assert len(results) == 3

        for result in results:
            assert "speaker" in result
            assert "original_claim" in result
            assert "consistency" in result

    async def test_check_claims_async_empty_list(self, mock_fact_checker):
        """check_claims_async returns empty list for empty input."""
        results = await mock_fact_checker.check_claims_async([])

        assert results == []

    async def test_check_claims_async_with_context(self, mock_fact_checker):
        """check_claims_async processes all claims when context is provided."""
        claims = [
            {"name": "A", "claim": "Claim 1"},
            {"name": "B", "claim": "Claim 2"},
        ]

        results = await mock_fact_checker.check_claims_async(claims, context="Hart aber Fair, 10.01.2024")

        assert len(results) == 2

    async def test_check_claims_async_handles_missing_fields(self, mock_fact_checker):
        """check_claims_async handles claims with missing name/claim fields."""
        claims = [
            {"claim": "Only claim, no name"},
            {"name": "Only name"},
            {},
        ]

        results = await mock_fact_checker.check_claims_async(claims)

        assert len(results) == 3
        # TestModel echoes the fixture speaker; the input falls back to "Unknown".
        assert results[0]["speaker"] in ["Unknown", "Test Speaker"]


class TestFactCheckerParallel:
    """Tests for parallel claim processing."""

    async def test_parallel_processing_enabled(self):
        """check_claims_async uses parallel processing when enabled."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
            "FACT_CHECK_PARALLEL": "true",
            "FACT_CHECK_MAX_WORKERS": "2",
        }):
            checker = FactChecker()

            assert checker.parallel_enabled is True
            assert checker.max_workers == 2

    async def test_parallel_processing_disabled_by_default(self):
        """Parallel processing is disabled when FACT_CHECK_PARALLEL is not 'true'."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
            "FACT_CHECK_PARALLEL": "false",
        }):
            checker = FactChecker()

            assert checker.parallel_enabled is False

    async def test_parallel_results_returned(self, mock_fact_check_response):
        """Parallel execution returns one result per claim."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
            "FACT_CHECK_PARALLEL": "true",
            "FACT_CHECK_MAX_WORKERS": "2",
        }):
            checker = FactChecker()

        fc_model = TestModel(call_tools=[], custom_output_args=mock_fact_check_response.model_dump())
        claims = [{"name": "A", "claim": "1"}, {"name": "B", "claim": "2"}, {"name": "C", "claim": "3"}]
        with checker.agent.override(model=fc_model), patch.object(checker, "critique_agent", None):
            results = await checker.check_claims_async(claims)

        assert len(results) == 3


class TestFactCheckerSync:
    """Tests for sync wrapper methods."""

    def test_check_claim_sync_wrapper(self, mock_fact_check_response):
        """check_claim() wraps async method for sync usage."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
        }):
            checker = FactChecker()

        fc_model = TestModel(call_tools=[], custom_output_args=mock_fact_check_response.model_dump())
        with checker.agent.override(model=fc_model), patch.object(checker, "critique_agent", None):
            result = checker.check_claim("Speaker", "Claim")

        assert isinstance(result, dict)
        assert "consistency" in result

    def test_check_claims_sync_wrapper(self, mock_fact_check_response):
        """check_claims() wraps async method for sync usage."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
        }):
            checker = FactChecker()

        fc_model = TestModel(call_tools=[], custom_output_args=mock_fact_check_response.model_dump())
        with checker.agent.override(model=fc_model), patch.object(checker, "critique_agent", None):
            claims = [{"name": "A", "claim": "B"}]
            results = checker.check_claims(claims)

        assert isinstance(results, list)
        assert len(results) == 1


class TestFactCheckerInit:
    """Tests for FactChecker initialization."""

    def test_init_default_model(self):
        """FactChecker uses default model when not specified."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
        }, clear=True):
            checker = FactChecker()
            assert checker.model_name == "gemini-2.5-pro"

    def test_init_default_request_limit(self):
        """FactChecker derives the request limit from FACT_CHECK_RECURSION_LIMIT."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
            "FACT_CHECK_RECURSION_LIMIT": "12",
        }):
            checker = FactChecker()
            assert checker.request_limit == 12

    def test_init_builds_agents(self):
        """FactChecker exposes the fact-check and critique agents."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
        }):
            checker = FactChecker()
            assert checker.agent is not None
            assert checker.critique_agent is not None

    def test_init_self_critique_disabled(self):
        """critique_agent is None when self-critique is disabled."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
            "SELF_CRITIQUE_ENABLED": "false",
        }):
            checker = FactChecker()
            assert checker.critique_agent is None
            assert checker.self_critique_enabled is False


class TestFactCheckResponse:
    """Tests for FactCheckResponse model."""

    def test_valid_response(self):
        """FactCheckResponse accepts valid data."""
        response = FactCheckResponse(
            speaker="Angela Merkel",
            original_claim="Test claim",
            consistency="hoch",
            evidence="Basierend auf offiziellen Quellen verifiziert.",
            sources=[
                Source(url="https://destatis.de", title="Statistisches Bundesamt"),
                Source(url="https://bundestag.de", title="Deutscher Bundestag"),
            ],
        )

        assert response.speaker == "Angela Merkel"
        assert response.consistency == "hoch"

    def test_consistency_literal_values(self):
        """FactCheckResponse consistency must be valid literal."""
        for valid_value in ["hoch", "niedrig", "unklar", "keine Datenlage"]:
            response = FactCheckResponse(
                speaker="Test",
                original_claim="Claim",
                consistency=valid_value,
                evidence="Evidence",
                sources=[],
            )
            assert response.consistency == valid_value

    def test_consistency_invalid_value(self):
        """FactCheckResponse rejects invalid consistency values."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            FactCheckResponse(
                speaker="Test",
                original_claim="Claim",
                consistency="invalid_value",
                evidence="Evidence",
                sources=[],
            )


class TestSelfCritique:
    """Tests for the self-critique step."""

    async def test_flagged_verdict_sets_double_check(self, mock_fact_checker):
        """double_check=True when critique returns low confidence."""
        flagged = SelfCritiqueResponse(
            confidence="low",
            reason="Der Begriff 'Energiepreise' ist weit gefasst.",
        )
        mock_fact_checker._critique_async = AsyncMock(return_value=flagged)

        result = await mock_fact_checker.check_claim_async("Speaker", "Eine Behauptung.")

        assert result["double_check"] is True
        assert result["critique_note"] == "Der Begriff 'Energiepreise' ist weit gefasst."

    async def test_high_confidence_does_not_flag(self, mock_fact_checker):
        """double_check=False when confidence is high."""
        not_flagged = SelfCritiqueResponse(confidence="high", reason="")
        mock_fact_checker._critique_async = AsyncMock(return_value=not_flagged)

        result = await mock_fact_checker.check_claim_async("Speaker", "Eine Behauptung.")

        assert result["double_check"] is False
        assert result["critique_note"] == ""

    async def test_critique_disabled_skips_call(self):
        """_critique_async returns defaults immediately when self_critique_enabled=False."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-key",
            "SELF_CRITIQUE_ENABLED": "false",
        }):
            checker = FactChecker()
            critique = await checker._critique_async("claim", "hoch", "evidence")

        assert critique.confidence == "high"
        assert critique.reason == ""

    async def test_critique_note_always_populated(self, mock_fact_checker):
        """critique_note is always set from the model's reason, even when double_check is False."""
        not_flagged = SelfCritiqueResponse(confidence="high", reason="Gut belegt.")
        mock_fact_checker._critique_async = AsyncMock(return_value=not_flagged)

        result = await mock_fact_checker.check_claim_async("Speaker", "Eine Behauptung.")

        assert result["double_check"] is False
        assert result["critique_note"] == "Gut belegt."
