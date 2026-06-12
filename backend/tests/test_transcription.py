"""Unit tests for TranscriptionService config building + keyterms derivation.

These mock the AssemblyAI SDK — no network, no API key needed beyond a dummy.
"""
from unittest.mock import MagicMock

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


class TestTranscribeConfig:
    def _service_capturing_config(self, monkeypatch):
        monkeypatch.setenv("ASSEMBLYAI_API_KEY", "dummy")
        captured = {}

        class FakeTranscriber:
            def __init__(self, *a, **k):
                pass

            def transcribe(self, audio, config=None):
                captured["config"] = config
                fake = MagicMock()
                fake.status = tr.aai.TranscriptStatus.completed
                fake.utterances = []
                fake.text = "ok"
                fake.audio_duration = 12.5
                return fake

        monkeypatch.setattr(tr.aai, "Transcriber", FakeTranscriber)
        return tr.TranscriptionService(), captured

    def test_uses_universal_3_pro_and_speaker_labels(self, monkeypatch):
        svc, captured = self._service_capturing_config(monkeypatch)
        svc.transcribe(b"audio")
        cfg = captured["config"]
        assert "universal-3-pro" in cfg.speech_models
        assert cfg.speaker_labels is True
        assert cfg.language_code == "de"

    def test_passes_keyterms_when_provided(self, monkeypatch):
        svc, captured = self._service_capturing_config(monkeypatch)
        svc.transcribe(b"audio", keyterms=["Heidi Reichinnek", "Linke"])
        assert captured["config"].keyterms_prompt == ["Heidi Reichinnek", "Linke"]

    def test_omits_keyterms_when_empty(self, monkeypatch):
        svc, captured = self._service_capturing_config(monkeypatch)
        svc.transcribe(b"audio", keyterms=[])
        assert captured["config"].keyterms_prompt is None

    def test_transcribe_returns_text_and_duration(self, monkeypatch):
        svc, _ = self._service_capturing_config(monkeypatch)
        text, duration = svc.transcribe(b"audio")
        assert text == "ok"   # no utterances -> formatter falls back to transcript.text
        assert duration == 12.5
