"""
Tests for ClaimExtractor setup and its input models.

The window gate and the reformulator are exercised in test_window_gate.py and
test_jev_gate.py.
"""

import pytest
from unittest.mock import patch

from backend.services.claim_extraction import ClaimExtractor, ClaimExtractionInput


class TestClaimExtractionInput:
    def test_has_conversation_type_and_no_date(self):
        assert "date" not in ClaimExtractionInput.model_fields
        assert "conversation_type" in ClaimExtractionInput.model_fields

    def test_has_excluded_speakers(self):
        assert "excluded_speakers" in ClaimExtractionInput.model_fields


class TestClaimExtractorInit:
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
            assert extractor.window_gate is not None
            assert extractor.reformulator is not None

    def test_init_reads_model_names_from_env(self):
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "test-key",
            "GEMINI_MODEL_WINDOW_GATE": "gemini-custom-gate",
            "GEMINI_MODEL_REFORMULATE": "gemini-custom-reformulate",
        }, clear=True):
            extractor = ClaimExtractor()
            assert extractor.window_model_name == "gemini-custom-gate"
            assert extractor.reformulate_model_name == "gemini-custom-reformulate"
