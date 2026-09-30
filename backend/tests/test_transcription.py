"""Unit tests for the AssemblyAI helpers: keyterms derivation and region host."""
import backend.services.transcription as tr
from backend.services.transcription import keyterms_from_guests


class TestKeytermsFromGuests:
    def test_splits_name_and_first_paren_segment(self):
        # name + party/org (first paren segment); role (2nd segment) is dropped
        assert keyterms_from_guests(["Heidi Reichinnek (Linke, Fraktionsvorsitzende)"]) == [
            "Heidi Reichinnek",
            "Linke",
        ]

    def test_plain_name_only(self):
        assert keyterms_from_guests(["Anna"]) == ["Anna"]

    def test_skips_empty_and_dedupes(self):
        assert keyterms_from_guests(["", "  ", "Bob (SPD)", "Bob (SPD)"]) == ["Bob", "SPD"]

    def test_empty_input(self):
        assert keyterms_from_guests([]) == []


class TestAssemblyaiRegion:
    def test_unset_keeps_assemblyai_defaults(self, monkeypatch):
        monkeypatch.delenv("ASSEMBLYAI_REGION", raising=False)
        assert tr.assemblyai_streaming_host() == "streaming.assemblyai.com"

    def test_eu_pins_streaming_host(self, monkeypatch):
        monkeypatch.setenv("ASSEMBLYAI_REGION", " EU ")
        assert tr.assemblyai_streaming_host() == "streaming.eu.assemblyai.com"

    def test_unknown_region_fails_loudly(self, monkeypatch):
        monkeypatch.setenv("ASSEMBLYAI_REGION", "europe")
        try:
            tr.assemblyai_streaming_host()
        except ValueError as e:
            assert "europe" in str(e)
        else:
            raise AssertionError("expected ValueError")
