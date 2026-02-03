"""
Tests for FactChecker service.

Tests:
- check_claim_async returns structured response
- Error handling returns "unklar" consistency
- check_claims_async processes multiple claims
"""

import pytest
from unittest.mock import MagicMock, patch

from backend.services.fact_checker import FactChecker, FactCheckResponse, Source


class TestFactCheckerCheckClaim:
    """Tests for FactChecker.check_claim_async()."""

    async def test_check_claim_returns_structured_response(self, mock_fact_checker, mock_fact_check_response):
        """check_claim_async returns properly structured response."""
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

    async def test_check_claim_with_context(self, mock_fact_checker, mock_create_agent):
        """check_claim_async passes context to agent."""
        await mock_fact_checker.check_claim_async(
            speaker="Test Speaker",
            claim="Test claim",
            context="Maischberger, 15.01.2024"
        )

        # Verify agent was called (uses invoke via asyncio.to_thread)
        mock_agent = mock_create_agent.return_value
        mock_agent.invoke.assert_called_once()

        # Check context was included in the message
        call_args = mock_agent.invoke.call_args[0][0]
        messages = call_args.get("messages", [])
        assert len(messages) > 0
        assert "Maischberger" in messages[0]["content"]

    async def test_check_claim_handles_error_gracefully(self, mock_create_agent):
        """check_claim_async returns 'unklar' on error."""
        # Make agent raise an exception (uses invoke via asyncio.to_thread)
        mock_agent = MagicMock()
        mock_agent.invoke = MagicMock(side_effect=Exception("Search API failed"))
        mock_create_agent.return_value = mock_agent

        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
        }):
            checker = FactChecker()

            result = await checker.check_claim_async(
                speaker="Test Speaker",
                claim="Some claim to verify"
            )

            assert result["consistency"] == "unklar"
            assert result["speaker"] == "Test Speaker"
            assert result["original_claim"] == "Some claim to verify"
            assert "Fehler" in result["evidence"]
            assert result["sources"] == []

    async def test_check_claim_uses_configured_model(self, mock_create_agent, mock_fact_check_response):
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

    async def test_check_claims_async_processes_list(self, mock_fact_checker, mock_create_agent):
        """check_claims_async processes multiple claims sequentially."""
        claims = [
            {"name": "Speaker A", "claim": "Claim 1"},
            {"name": "Speaker B", "claim": "Claim 2"},
            {"name": "Speaker C", "claim": "Claim 3"},
        ]

        results = await mock_fact_checker.check_claims_async(claims)

        assert isinstance(results, list)
        assert len(results) == 3

        # Each result should have the expected structure
        for result in results:
            assert "speaker" in result
            assert "original_claim" in result
            assert "consistency" in result

    async def test_check_claims_async_empty_list(self, mock_fact_checker):
        """check_claims_async returns empty list for empty input."""
        results = await mock_fact_checker.check_claims_async([])

        assert results == []

    async def test_check_claims_async_with_context(self, mock_fact_checker, mock_create_agent):
        """check_claims_async passes context to all claims."""
        claims = [
            {"name": "A", "claim": "Claim 1"},
            {"name": "B", "claim": "Claim 2"},
        ]

        await mock_fact_checker.check_claims_async(claims, context="Hart aber Fair, 10.01.2024")

        # Agent should be called for each claim (uses invoke via asyncio.to_thread)
        mock_agent = mock_create_agent.return_value
        assert mock_agent.invoke.call_count == 2

    async def test_check_claims_async_handles_missing_fields(self, mock_fact_checker):
        """check_claims_async handles claims with missing name/claim fields."""
        claims = [
            {"claim": "Only claim, no name"},
            {"name": "Only name"},
            {},
        ]

        results = await mock_fact_checker.check_claims_async(claims)

        assert len(results) == 3
        # Should use "Unknown" for missing name
        assert results[0]["speaker"] in ["Unknown", "Test Speaker"]


class TestFactCheckerParallel:
    """Tests for parallel claim processing."""

    async def test_parallel_processing_enabled(self, mock_create_agent, mock_fact_check_response):
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

    async def test_parallel_processing_disabled_by_default(self, mock_create_agent, mock_fact_check_response):
        """Parallel processing is disabled when FACT_CHECK_PARALLEL is not 'true'."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
            "FACT_CHECK_PARALLEL": "false",
        }):
            checker = FactChecker()

            assert checker.parallel_enabled is False


class TestFactCheckerSync:
    """Tests for sync wrapper methods."""

    def test_check_claim_sync_wrapper(self, mock_create_agent, mock_fact_check_response):
        """check_claim() wraps async method for sync usage."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
        }):
            checker = FactChecker()

            result = checker.check_claim("Speaker", "Claim")

            assert isinstance(result, dict)
            assert "consistency" in result

    def test_check_claims_sync_wrapper(self, mock_create_agent, mock_fact_check_response):
        """check_claims() wraps async method for sync usage."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
        }):
            checker = FactChecker()

            claims = [{"name": "A", "claim": "B"}]
            results = checker.check_claims(claims)

            assert isinstance(results, list)
            assert len(results) == 1


class TestFactCheckerInit:
    """Tests for FactChecker initialization."""

    def test_init_requires_gemini_api_key(self):
        """FactChecker raises error without Gemini API key."""
        with patch.dict("os.environ", {"TAVILY_API_KEY": "tavily-key"}, clear=True):
            import os
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.pop("GOOGLE_API_KEY", None)

            with pytest.raises(ValueError) as exc_info:
                FactChecker()

            assert "GEMINI_API_KEY" in str(exc_info.value) or "GOOGLE_API_KEY" in str(exc_info.value)

    def test_init_requires_tavily_api_key(self, mock_create_agent):
        """FactChecker raises error without Tavily API key."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "gemini-key"}, clear=True):
            import os
            os.environ.pop("TAVILY_API_KEY", None)

            with pytest.raises(ValueError) as exc_info:
                FactChecker()

            assert "TAVILY_API_KEY" in str(exc_info.value)

    def test_init_default_model(self, mock_create_agent):
        """FactChecker uses default model when not specified."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
        }):
            import os
            os.environ.pop("GEMINI_MODEL_FACT_CHECKER", None)

            checker = FactChecker()
            assert checker.model_name == "gemini-2.5-pro"

    def test_init_search_config(self, mock_create_agent):
        """FactChecker uses search config from environment."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "TAVILY_API_KEY": "test-tavily-key",
            "TAVILY_SEARCH_DEPTH": "advanced",
            "TAVILY_MAX_RESULTS": "10",
        }):
            checker = FactChecker()

            assert checker.search_depth == "advanced"
            assert checker.max_results == 10


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
        for valid_value in ["hoch", "niedrig", "mittel", "unklar"]:
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
