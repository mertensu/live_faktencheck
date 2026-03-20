"""
Tests for shared utility functions.
"""

from backend.utils import build_fact_check_dict


class TestBuildFactCheckDict:
    """Tests for build_fact_check_dict."""

    def test_basic_fields(self):
        """Maps LLM result fields to DB field names."""
        result = build_fact_check_dict(
            {
                "speaker": "Angela Merkel",
                "original_claim": "Deutschland hat 80 Mio. Einwohner.",
                "consistency": "hoch",
                "evidence": "Laut Statistischem Bundesamt korrekt.",
                "sources": [{"url": "https://destatis.de", "title": "Destatis"}],
            },
            episode_key="maischberger-2026-01",
        )

        assert result["sprecher"] == "Angela Merkel"
        assert result["behauptung"] == "Deutschland hat 80 Mio. Einwohner."
        assert result["consistency"] == "hoch"
        assert result["begruendung"] == "Laut Statistischem Bundesamt korrekt."
        assert result["quellen"] == [{"url": "https://destatis.de", "title": "Destatis"}]
        assert result["episode_key"] == "maischberger-2026-01"

    def test_double_check_defaults_to_false(self):
        """double_check and critique_note default to False / '' when absent."""
        result = build_fact_check_dict(
            {"speaker": "S", "original_claim": "C", "consistency": "unklar", "evidence": "", "sources": []},
            episode_key="ep",
        )

        assert result["double_check"] is False
        assert result["critique_note"] == ""

    def test_double_check_passed_through(self):
        """double_check=True and critique_note are forwarded from the LLM result."""
        result = build_fact_check_dict(
            {
                "speaker": "S",
                "original_claim": "C",
                "consistency": "unklar",
                "evidence": "",
                "sources": [],
                "double_check": True,
                "critique_note": "Sehr wortlautabhängig.",
            },
            episode_key="ep",
        )

        assert result["double_check"] is True
        assert result["critique_note"] == "Sehr wortlautabhängig."

    def test_speaker_and_claim_fallbacks(self):
        """Uses fallback values when speaker/original_claim are missing."""
        result = build_fact_check_dict(
            {"consistency": "unklar", "evidence": "", "sources": []},
            episode_key="ep",
            speaker_fallback="Fallback Speaker",
            claim_fallback="Fallback claim",
        )

        assert result["sprecher"] == "Fallback Speaker"
        assert result["behauptung"] == "Fallback claim"
