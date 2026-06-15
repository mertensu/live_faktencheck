"""
Tests for ClaimExtractor service (PydanticAI backend).

Tests:
- extract_async / extract_claims_async return claim lists
- Error handling for model failures
- Speaker label resolution and the split resolve/extract methods
- Autopilot selection
"""

import pytest
from unittest.mock import patch

from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.messages import ModelMessage, ModelResponse

from backend.services.claim_extraction import (
    ClaimExtractor, ClaimList, ExtractedClaim, ResolvedTranscript, SpeakerLabelMapping,
)


def _empty_claims_model() -> TestModel:
    """A TestModel that returns an empty ClaimList."""
    return TestModel(custom_output_args=ClaimList(claims=[]).model_dump())


class TestClaimExtractorExtract:
    """Tests for ClaimExtractor.extract_async() / extract_claims_async()."""

    async def test_extract_claims_async_returns_claim_list(self, mock_claim_extractor, mock_gemini_response):
        """extract_claims_async returns list of ExtractedClaim objects."""
        transcript = """
        Speaker A: Deutschland hat über 80 Millionen Einwohner.
        Speaker B: Die Wirtschaft wächst um 2 Prozent.
        """
        guests = ["Speaker A (Politician)", "Speaker B (Economist)"]

        result = await mock_claim_extractor.extract_claims_async(transcript, guests)

        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(c, ExtractedClaim) for c in result)
        assert result[0].name == "Test Speaker"
        assert result[0].claim == "Test claim statement"

    async def test_extract_passes_correct_content(self, mock_claim_extractor):
        """extract_async forwards the transcript and context to the model as the user message."""
        captured = {}

        async def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            # Record the user prompt the agent sent to the model.
            for part in messages[-1].parts:
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    captured["user_message"] = content
            return await _empty_claims_model().request(messages, info.model_settings, info.model_request_parameters)

        with mock_claim_extractor.claim_extractor.override(model=FunctionModel(capture)):
            await mock_claim_extractor.extract_claims_async(
                "Test transcript content", ["Speaker A (Politiker)"], context="Context information"
            )

        assert "Test transcript content" in captured["user_message"]
        assert "Context information" in captured["user_message"]

    def test_claim_extraction_input_drops_date_adds_conversation_type(self):
        """The date field is gone; conversation_type is present."""
        from backend.services.claim_extraction import ClaimExtractionInput, SpeakerLabelsInput
        assert "date" not in ClaimExtractionInput.model_fields
        assert "conversation_type" in ClaimExtractionInput.model_fields
        assert "conversation_type" in SpeakerLabelsInput.model_fields

    async def test_extract_passes_conversation_type(self, mock_claim_extractor):
        """conversation_type reaches the model as part of the user message."""
        captured = {}

        async def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            for part in messages[-1].parts:
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    captured["user_message"] = content
            return await _empty_claims_model().request(messages, info.model_settings, info.model_request_parameters)

        with mock_claim_extractor.claim_extractor.override(model=FunctionModel(capture)):
            await mock_claim_extractor.extract_claims_async(
                "Test transcript", ["Speaker A"], conversation_type="private"
            )

        assert "private" in captured["user_message"]

    def test_claim_extraction_input_has_excluded_speakers(self):
        from backend.services.claim_extraction import ClaimExtractionInput
        assert "excluded_speakers" in ClaimExtractionInput.model_fields

    async def test_extract_passes_excluded_speakers(self, mock_claim_extractor):
        """excluded_speakers reaches the model as part of the user message."""
        captured = {}

        async def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            for part in messages[-1].parts:
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    captured["user_message"] = content
            return await _empty_claims_model().request(messages, info.model_settings, info.model_request_parameters)

        with mock_claim_extractor.claim_extractor.override(model=FunctionModel(capture)):
            await mock_claim_extractor.extract_claims_async(
                "Test transcript", ["Anna Müller"], excluded_speakers=["Zacharias Übeltäter"]
            )

        # "Zacharias Übeltäter" is not in guests, so it can only appear in the serialized
        # message if excluded_speakers was actually forwarded into ClaimExtractionInput.
        assert "excluded_speakers" in captured["user_message"]
        assert "Zacharias Übeltäter" in captured["user_message"]

    def test_extract_uses_configured_model(self):
        """ClaimExtractor reads the model name from the environment."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL_CLAIM_EXTRACTION": "gemini-custom-model",
        }):
            extractor = ClaimExtractor()
            assert extractor.model_name == "gemini-custom-model"

    async def test_extract_handles_model_error(self):
        """extract_async propagates exceptions raised by the model."""
        async def boom(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise RuntimeError("API rate limit exceeded")

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()

        with extractor.claim_extractor.override(model=FunctionModel(boom)):
            with pytest.raises(Exception) as exc_info:
                await extractor.extract_claims_async("transcript", [])

        assert "API rate limit exceeded" in str(exc_info.value)

    async def test_extract_empty_transcript(self, mock_claim_extractor):
        """extract_async handles empty transcript (full path incl. resolution)."""
        with mock_claim_extractor.speaker_resolver.override(
            model=TestModel(custom_output_args=ResolvedTranscript(mappings=[]).model_dump())
        ):
            result = await mock_claim_extractor.extract_async("", [])

        assert isinstance(result, list)


class TestClaimExtractorSync:
    """Tests for sync wrapper methods."""

    def test_extract_sync_wrapper(self, mock_gemini_response):
        """extract() wraps extract_async() for sync usage."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()

        claims_model = TestModel(custom_output_args=mock_gemini_response.model_dump())
        with extractor.claim_extractor.override(model=claims_model), \
             extractor.speaker_resolver.override(model=TestModel(custom_output_args=ResolvedTranscript(mappings=[]).model_dump())):
            result = extractor.extract("transcript", [])

        assert isinstance(result, list)
        assert len(result) == 2


class TestClaimExtractorInit:
    """Tests for ClaimExtractor initialization."""

    def test_init_requires_api_key(self):
        """ClaimExtractor raises error without API key."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                ClaimExtractor()

            assert "API_KEY" in str(exc_info.value)

    def test_init_accepts_google_api_key(self):
        """ClaimExtractor accepts GOOGLE_API_KEY as alternative."""
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "google-key"}, clear=True):
            extractor = ClaimExtractor()
            assert extractor.claim_extractor is not None

    def test_init_default_model(self):
        """ClaimExtractor uses default model when not specified."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=True):
            extractor = ClaimExtractor()
            assert extractor.model_name == "gemini-2.5-flash"


class TestSpeakerLabelResolution:
    """Tests for speaker label resolution (step 1 of claim extraction)."""

    async def test_resolve_labels_applies_mappings(self, mock_claim_extractor):
        """resolve_labels_async applies the LLM-supplied label->name mappings."""
        resolver_out = ResolvedTranscript(mappings=[SpeakerLabelMapping(label="Speaker A", name="Julia Berger")])
        with mock_claim_extractor.speaker_resolver.override(
            model=TestModel(custom_output_args=resolver_out.model_dump())
        ):
            resolved = await mock_claim_extractor.resolve_labels_async(
                "Speaker A: Hallo.", guests=["Julia Berger (CDU)"]
            )
        assert resolved == "Julia Berger: Hallo."

    async def test_resolve_labels_replaces_longest_first(self, mock_claim_extractor):
        """Overlapping labels resolve correctly: the longer label is not corrupted by the shorter."""
        resolver_out = ResolvedTranscript(mappings=[
            SpeakerLabelMapping(label="Sprecher A", name="Anna Müller"),
            SpeakerLabelMapping(label="Sprecher AB", name="Bert Klein"),
        ])
        with mock_claim_extractor.speaker_resolver.override(
            model=TestModel(custom_output_args=resolver_out.model_dump())
        ):
            resolved = await mock_claim_extractor.resolve_labels_async(
                "Sprecher AB: Hallo. Sprecher A: Tschüss.",
                guests=["Anna Müller (CDU)", "Bert Klein (SPD)"],
            )
        # The longer label must map to Bert Klein, not get corrupted into "Anna MüllerB".
        assert resolved == "Bert Klein: Hallo. Anna Müller: Tschüss."

    async def test_resolve_runs_before_extraction(self, mock_claim_extractor):
        """extract_async resolves speaker labels first, then extracts from the resolved transcript."""
        resolver_out = ResolvedTranscript(mappings=[SpeakerLabelMapping(label="Sprecher A", name="Anna Müller")])
        captured = {}

        async def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            for part in messages[-1].parts:
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    captured["user_message"] = content
            return await _empty_claims_model().request(messages, info.model_settings, info.model_request_parameters)

        with mock_claim_extractor.speaker_resolver.override(model=TestModel(custom_output_args=resolver_out.model_dump())), \
             mock_claim_extractor.claim_extractor.override(model=FunctionModel(capture)):
            await mock_claim_extractor.extract_async(
                "Sprecher A: Die Wirtschaft wächst.", ["Anna Müller (Moderatorin)"]
            )

        # The resolved name reaches the extraction model; the generic label is gone.
        assert "Anna Müller" in captured["user_message"]
        assert "Sprecher A" not in captured["user_message"]

    async def test_resolve_skipped_when_no_resolver(self):
        """resolve_labels_async returns the transcript unchanged when no resolver is configured."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()
            extractor.speaker_resolver = None

            result = await extractor.resolve_labels_async("Sprecher A: Hallo.", ["Anna Müller"])

        assert result == "Sprecher A: Hallo."


class TestClaimExtractorSplitMethods:
    """Tests for the split resolve/extract methods."""

    async def test_extract_claims_async_skips_resolution(self, mock_claim_extractor):
        """extract_claims_async does NOT invoke the speaker resolver."""
        async def boom(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise AssertionError("speaker resolver must not be called by extract_claims_async")

        with mock_claim_extractor.speaker_resolver.override(model=FunctionModel(boom)):
            result = await mock_claim_extractor.extract_claims_async(
                "Anna Müller: Die Wirtschaft wächst.", ["Anna Müller"]
            )

        assert isinstance(result, list)

    async def test_extract_claims_async_passes_previous_block_ending(self, mock_claim_extractor):
        """extract_claims_async includes previous_block_ending in the user message."""
        captured = {}

        async def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            for part in messages[-1].parts:
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    captured["user_message"] = content
            return await _empty_claims_model().request(messages, info.model_settings, info.model_request_parameters)

        with mock_claim_extractor.claim_extractor.override(model=FunctionModel(capture)):
            await mock_claim_extractor.extract_claims_async(
                "transcript", [], previous_context="Anna Müller: letzter Satz."
            )

        assert "Anna Müller: letzter Satz." in captured["user_message"]


class TestClaimSelection:
    """Tests for autopilot claim selection."""

    async def test_select_returns_dicts_capped(self, mock_claim_extractor):
        """select_async returns at most max_claims claim dicts."""
        claims = [
            {"name": "A", "claim": "claim 1"},
            {"name": "B", "claim": "claim 2"},
            {"name": "C", "claim": "claim 3"},
        ]
        # mock_claim_extractor's selection_agent returns two claims (mock_gemini_response).
        result = await mock_claim_extractor.select_async(claims, max_claims=1)

        assert isinstance(result, list)
        assert len(result) <= 1
        assert all(set(c.keys()) == {"name", "claim"} for c in result)

    async def test_select_falls_back_on_error(self):
        """select_async returns the input claims (capped) if the model errors."""
        async def boom(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            raise RuntimeError("selection failed")

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()

        claims = [{"name": "A", "claim": "c1"}, {"name": "B", "claim": "c2"}]
        with extractor.selection_agent.override(model=FunctionModel(boom)):
            result = await extractor.select_async(claims, max_claims=1)

        assert result == claims[:1]
