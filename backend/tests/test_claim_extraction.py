"""
Tests for ClaimExtractor service.

Tests:
- extract_async returns claim list
- Error handling for API failures
- Article extraction path
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.claim_extraction import ClaimExtractor, ExtractedClaim, ClaimList


class TestClaimExtractorExtract:
    """Tests for ClaimExtractor.extract_async()."""

    async def test_extract_returns_claim_list(self, mock_claim_extractor, mock_gemini_response):
        """extract_async returns list of ExtractedClaim objects."""
        transcript = """
        Speaker A: Deutschland hat über 80 Millionen Einwohner.
        Speaker B: Die Wirtschaft wächst um 2 Prozent.
        """
        info = "Talkshow guests: Speaker A (Politician), Speaker B (Economist)"

        result = await mock_claim_extractor.extract_async(transcript, info)

        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(c, ExtractedClaim) for c in result)
        assert result[0].name == "Test Speaker"
        assert result[0].claim == "Test claim statement"

    async def test_extract_passes_correct_content(self, mock_genai_client, mock_gemini_response):
        """extract_async passes transcript and info to Gemini."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()

            transcript = "Test transcript content"
            info = "Context information"

            await extractor.extract_async(transcript, info)

            # Verify generate_content was called
            mock_genai_client.aio.models.generate_content.assert_called_once()

            # Check the content includes transcript and info
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
                await extractor.extract_async("transcript", "info")

            assert "API rate limit exceeded" in str(exc_info.value)

    async def test_extract_empty_transcript(self, mock_claim_extractor):
        """extract_async handles empty transcript."""
        # The mock will still return claims, but this tests the call works
        result = await mock_claim_extractor.extract_async("", "")

        assert isinstance(result, list)


class TestClaimExtractorArticle:
    """Tests for ClaimExtractor.extract_from_article_async()."""

    async def test_extract_from_article(self, mock_claim_extractor, mock_gemini_response):
        """extract_from_article_async returns claims from article text."""
        article_text = """
        Die Bundesregierung hat beschlossen, dass die Strompreise um 10% sinken werden.
        Laut dem Wirtschaftsminister wird dies ab nächstem Jahr gelten.
        """
        headline = "Strompreise sollen 2024 sinken"

        result = await mock_claim_extractor.extract_from_article_async(article_text, headline)

        assert isinstance(result, list)
        assert len(result) == 2  # From mock response

    async def test_extract_from_article_with_date(self, mock_genai_client, mock_gemini_response):
        """extract_from_article_async uses provided publication date."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()

            await extractor.extract_from_article_async(
                text="Article content",
                headline="Test Headline",
                publication_date="Januar 2024"
            )

            # Verify the prompt was called (date is embedded in system prompt)
            mock_genai_client.aio.models.generate_content.assert_called_once()

    async def test_extract_from_article_default_date(self, mock_genai_client, mock_gemini_response):
        """extract_from_article_async defaults to current month/year."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()

            # Call without publication_date
            await extractor.extract_from_article_async(
                text="Article content",
                headline="Test Headline"
            )

            mock_genai_client.aio.models.generate_content.assert_called_once()

    async def test_extract_from_article_includes_headline(self, mock_genai_client, mock_gemini_response):
        """extract_from_article_async includes headline in user message."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()

            await extractor.extract_from_article_async(
                text="Some article text",
                headline="Important Breaking News"
            )

            call_args = mock_genai_client.aio.models.generate_content.call_args
            contents = call_args.kwargs.get("contents", call_args[1].get("contents", ""))
            assert "Important Breaking News" in contents
            assert "Some article text" in contents


class TestClaimExtractorSync:
    """Tests for sync wrapper methods."""

    def test_extract_sync_wrapper(self, mock_genai_client, mock_gemini_response):
        """extract() wraps extract_async() for sync usage."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()

            result = extractor.extract("transcript", "info")

            assert isinstance(result, list)
            assert len(result) == 2

    def test_extract_from_article_sync_wrapper(self, mock_genai_client, mock_gemini_response):
        """extract_from_article() wraps async method for sync usage."""
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            extractor = ClaimExtractor()

            result = extractor.extract_from_article("text", "headline")

            assert isinstance(result, list)
            assert len(result) == 2


class TestClaimExtractorInit:
    """Tests for ClaimExtractor initialization."""

    def test_init_requires_api_key(self):
        """ClaimExtractor raises error without API key."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove both possible API key env vars
            import os
            os.environ.pop("GEMINI_API_KEY", None)
            os.environ.pop("GOOGLE_API_KEY", None)

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
        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            # Remove model env var if present
            import os
            os.environ.pop("GEMINI_MODEL_CLAIM_EXTRACTION", None)

            extractor = ClaimExtractor()
            assert extractor.model_name == "gemini-2.5-flash"
