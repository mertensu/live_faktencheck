"""
Tests for ClaimExtractor service.

Tests:
- extract_async returns claim list
- Error handling for API failures
- Article extraction path
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.claim_extraction import (
    ClaimExtractor, ExtractedClaim, ResolvedTranscript, SpeakerLabelMapping,
)


class TestClaimExtractorExtract:
    """Tests for ClaimExtractor.extract_async()."""

    async def test_extract_returns_claim_list(self, mock_claim_extractor, mock_gemini_response):
        """extract_async returns list of ExtractedClaim objects."""
        transcript = """
        Speaker A: Deutschland hat über 80 Millionen Einwohner.
        Speaker B: Die Wirtschaft wächst um 2 Prozent.
        """
        guests = ["Speaker A (Politician)", "Speaker B (Economist)"]

        result = await mock_claim_extractor.extract_async(transcript, guests)

        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(c, ExtractedClaim) for c in result)
        assert result[0].name == "Test Speaker"
        assert result[0].claim == "Test claim statement"

    async def test_extract_passes_correct_content(self, mock_genai_client, mock_gemini_response):
        """extract_async passes transcript and info to Gemini."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()
            extractor.speaker_labels_prompt_template = None

            transcript = "Test transcript content"
            guests = ["Speaker A (Politiker)"]
            context = "Context information"

            await extractor.extract_async(transcript, guests, context=context)

            # Verify generate_content was called
            mock_genai_client.aio.models.generate_content.assert_called_once()

            # Check the content includes transcript and context
            call_args = mock_genai_client.aio.models.generate_content.call_args
            contents = call_args.kwargs.get("contents", call_args[1].get("contents", ""))
            assert "Test transcript content" in contents
            assert "Context information" in contents

    async def test_extract_uses_configured_model(self, mock_genai_client, mock_gemini_response):
        """extract_async uses model from environment."""
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL_CLAIM_EXTRACTION": "gemini-custom-model",
        }):
            extractor = ClaimExtractor()

            assert extractor.model_name == "gemini-custom-model"

    async def test_extract_handles_api_error(self, mock_genai_client):
        """extract_async raises exception on API error."""
        mock_genai_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("API rate limit exceeded")
        )

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()

            with pytest.raises(Exception) as exc_info:
                await extractor.extract_async("transcript", [])

            assert "API rate limit exceeded" in str(exc_info.value)

    async def test_extract_empty_transcript(self, mock_claim_extractor):
        """extract_async handles empty transcript."""
        # The mock will still return claims, but this tests the call works
        result = await mock_claim_extractor.extract_async("", [])

        assert isinstance(result, list)


class TestClaimExtractorSync:
    """Tests for sync wrapper methods."""

    def test_extract_sync_wrapper(self, mock_genai_client, mock_gemini_response):
        """extract() wraps extract_async() for sync usage."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()
            extractor.speaker_labels_prompt_template = None

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

    def test_init_accepts_google_api_key(self, mock_genai_client):
        """ClaimExtractor accepts GOOGLE_API_KEY as alternative."""
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "google-key"}, clear=True):
            extractor = ClaimExtractor()
            assert extractor.client is not None

    def test_init_default_model(self, mock_genai_client):
        """ClaimExtractor uses default model when not specified."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=True):
            extractor = ClaimExtractor()
            assert extractor.model_name == "gemini-2.5-flash"


class TestSpeakerLabelResolution:
    """Tests for speaker label resolution (step 1 of claim extraction)."""

    async def test_resolve_speaker_labels_called_before_extraction(self, mock_genai_client, mock_gemini_response):
        """_resolve_speaker_labels_async is called before _extract_async and its output is forwarded."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()
            extractor.speaker_labels_prompt_template = "fake speaker labels prompt"

            resolved = "Resolved transcript content"
            extractor._resolve_speaker_labels_async = AsyncMock(return_value=resolved)

            captured = {}
            original_extract = extractor._extract_async

            async def capture_extract(system_prompt, user_message):
                captured["user_message"] = user_message
                return await original_extract(system_prompt, user_message)

            extractor._extract_async = capture_extract

            guests = ["Anna Müller (Moderatorin)", "Karl Schmidt (CDU)"]
            await extractor.extract_async("Original transcript", guests)

            extractor._resolve_speaker_labels_async.assert_called_once_with("Original transcript", guests)
            assert resolved in captured["user_message"]

    async def test_resolve_speaker_labels_uses_structured_output(self, mock_genai_client):
        """_resolve_speaker_labels_async calls Gemini with ResolvedTranscript schema and applies mappings."""
        # Set up two sequential responses: ResolvedTranscript then ClaimList
        from backend.services.claim_extraction import ClaimList

        resolution_response = MagicMock()
        resolution_response.parsed = ResolvedTranscript(mappings=[
            SpeakerLabelMapping(label="Sprecher A", name="Anna Müller"),
        ])
        extraction_response = MagicMock()
        extraction_response.parsed = ClaimList(claims=[])
        mock_genai_client.aio.models.generate_content = AsyncMock(
            side_effect=[resolution_response, extraction_response]
        )

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()
            extractor.speaker_labels_prompt_template = "fake speaker labels prompt"

            transcript = "Sprecher A: Die Wirtschaft wächst."
            result_transcript = await extractor._resolve_speaker_labels_async(transcript, ["Anna Müller (Moderatorin)"])

        assert "Anna Müller" in result_transcript
        assert "Sprecher A" not in result_transcript

        resolution_call = mock_genai_client.aio.models.generate_content.call_args_list[0]
        config = resolution_call.kwargs.get("config", {})
        assert config.get("response_mime_type") == "application/json"
        assert config.get("response_schema") is ResolvedTranscript

    async def test_resolve_skipped_if_prompt_not_loaded(self, mock_genai_client, mock_gemini_response):
        """Speaker label resolution is skipped when speaker_labels_prompt_template is None."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()
            extractor.speaker_labels_prompt_template = None
            extractor._resolve_speaker_labels_async = AsyncMock()

            await extractor.extract_async("raw transcript", [])

            extractor._resolve_speaker_labels_async.assert_not_called()


class TestClaimExtractorSplitMethods:
    """Tests for the split resolve/extract methods."""

    async def test_resolve_labels_async_returns_resolved(self, mock_genai_client):
        """resolve_labels_async applies mappings from LLM to the transcript."""
        resolution_response = MagicMock()
        resolution_response.parsed = ResolvedTranscript(mappings=[
            SpeakerLabelMapping(label="Sprecher A", name="Anna Müller"),
        ])
        mock_genai_client.aio.models.generate_content = AsyncMock(return_value=resolution_response)

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()
            extractor.speaker_labels_prompt_template = "fake prompt"

            result = await extractor.resolve_labels_async("Sprecher A: Hallo.", ["Anna Müller"])

        assert "Anna Müller" in result
        assert "Sprecher A" not in result

    async def test_resolve_labels_async_passthrough_when_no_prompt(self, mock_genai_client):
        """resolve_labels_async returns transcript unchanged when no speaker labels prompt."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()
            extractor.speaker_labels_prompt_template = None

            result = await extractor.resolve_labels_async("Sprecher A: Hallo.", ["Anna Müller"])

        assert result == "Sprecher A: Hallo."

    async def test_extract_claims_async_skips_resolution(self, mock_genai_client, mock_gemini_response):
        """extract_claims_async does NOT call speaker label resolution."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()
            extractor.speaker_labels_prompt_template = "fake prompt"
            extractor._resolve_speaker_labels_async = AsyncMock()

            await extractor.extract_claims_async("Anna Müller: Die Wirtschaft wächst.", ["Anna Müller"])

            extractor._resolve_speaker_labels_async.assert_not_called()

    async def test_extract_claims_async_passes_previous_block_ending(self, mock_genai_client, mock_gemini_response):
        """extract_claims_async includes previous_block_ending in user message."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()
            extractor.speaker_labels_prompt_template = None

            captured = {}
            original = extractor._extract_async
            async def capture(system_prompt, user_message):
                captured["user_message"] = user_message
                return await original(system_prompt, user_message)
            extractor._extract_async = capture

            await extractor.extract_claims_async(
                "transcript", [], previous_context="Anna Müller: letzter Satz."
            )

        assert "Anna Müller: letzter Satz." in captured["user_message"]
