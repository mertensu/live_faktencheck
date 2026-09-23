"""
Unit tests for voiceprint speaker identification (backend/services/speaker_id.py).

The embedding is stubbed via ``_embed_fn`` so these tests never import sherpa-onnx /
onnxruntime — only the argmax/threshold/min_seconds gating, voiceprint loading, and the
PCM conversion are exercised. Accuracy on real audio lives in the offline bench
(benchmarks/speaker_id_bench.py), not here.
"""

import numpy as np
import pytest

from backend.services.speaker_id import (
    SpeakerIdentifier,
    load_voiceprints,
    pcm16_to_float32,
)


# Two orthogonal unit voiceprints in a tiny space; embeddings are stubbed to pick one.
PRINTS = {"Alice": np.array([1.0, 0.0, 0.0], np.float32),
          "Bob": np.array([0.0, 1.0, 0.0], np.float32)}


def _ident(embed_vec, *, threshold=0.55, min_seconds=0.0, prints=PRINTS):
    """A SpeakerIdentifier whose _embed always returns ``embed_vec``."""
    return SpeakerIdentifier(
        "unused-model", prints,
        threshold=threshold, min_seconds=min_seconds,
        _embed_fn=lambda pcm, sr: np.asarray(embed_vec, np.float32),
    )


def _pcm(n=1600):
    return np.zeros(n, np.float32)


class TestIdentify:
    def test_confident_argmax_accepts(self):
        # Embedding aligned with Alice -> cosine 1.0 >= threshold.
        name, top = _ident([1.0, 0.0, 0.0]).identify(_pcm())
        assert name == "Alice"
        assert top == pytest.approx(1.0)

    def test_argmax_picks_nearest_of_several(self):
        name, _ = _ident([0.1, 0.9, 0.0]).identify(_pcm())
        assert name == "Bob"

    def test_below_threshold_returns_none_but_reports_top(self):
        # Halfway between the two prints -> cosine ~0.707 to each; raise the bar above it.
        name, top = _ident([1.0, 1.0, 0.0], threshold=0.9).identify(_pcm())
        assert name is None
        assert top == pytest.approx(1 / np.sqrt(2), rel=1e-3)

    def test_too_short_short_circuits(self):
        # 0.5 s at 16 kHz is below min_seconds -> no embedding attempted.
        ident = _ident([1.0, 0.0, 0.0], min_seconds=1.5)
        assert ident.identify(np.zeros(8000, np.float32), sr=16000) == (None, 0.0)

    def test_empty_voiceprints_short_circuits(self):
        ident = _ident([1.0, 0.0, 0.0], prints={})
        assert ident.identify(_pcm()) == (None, 0.0)

    def test_min_seconds_boundary_uses_given_sr(self):
        # Exactly min_seconds worth of samples is accepted (>=, not >).
        ident = _ident([1.0, 0.0, 0.0], min_seconds=1.0)
        name, _ = ident.identify(np.zeros(16000, np.float32), sr=16000)
        assert name == "Alice"


class TestLoadVoiceprints:
    def test_round_trip_and_normalization(self, tmp_path):
        np.save(tmp_path / "Alice.npy", np.array([3.0, 4.0, 0.0], np.float32))  # norm 5
        prints = load_voiceprints(tmp_path)
        assert set(prints) == {"Alice"}
        assert np.linalg.norm(prints["Alice"]) == pytest.approx(1.0)

    def test_case_insensitive_guest_filter(self, tmp_path):
        for n in ("Alice", "Bob", "Carol"):
            np.save(tmp_path / f"{n}.npy", np.array([1.0, 0.0], np.float32))
        prints = load_voiceprints(tmp_path, names=["alice", "BOB"])
        assert set(prints) == {"Alice", "Bob"}

    def test_umlaut_matches_across_unicode_forms(self, tmp_path):
        import unicodedata
        decomposed = unicodedata.normalize("NFD", "Dröge")
        np.save(tmp_path / f"{decomposed}.npy", np.array([1.0, 0.0], np.float32))
        prints = load_voiceprints(tmp_path, ["Dröge"])  # composed, as typed in the guest list
        assert list(prints) == ["Dröge"]

    def test_missing_directory_is_empty(self, tmp_path):
        assert load_voiceprints(tmp_path / "nope") == {}


class TestPcmConversion:
    def test_known_bytes(self):
        # int16 0, 32767, -32768 -> ~0, ~+1, -1
        raw = np.array([0, 32767, -32768], "<i2").tobytes()
        out = pcm16_to_float32(raw)
        assert out.dtype == np.float32
        np.testing.assert_allclose(out, [0.0, 32767 / 32768, -1.0], atol=1e-6)


class TestRegistryFactory:
    def test_disabled_by_default(self, monkeypatch):
        from backend.services.registry import get_speaker_identifier
        monkeypatch.delenv("SPEAKER_ID_ENABLED", raising=False)
        assert get_speaker_identifier(["Alice"]) is None

    def test_enabled_without_model_returns_none(self, monkeypatch, tmp_path):
        from backend.services.registry import get_speaker_identifier
        # A real voiceprint exists, but no model path -> still None (can't embed).
        np.save(tmp_path / "Alice.npy", np.array([1.0, 0.0], np.float32))
        monkeypatch.setenv("SPEAKER_ID_ENABLED", "true")
        monkeypatch.delenv("SPEAKER_ID_MODEL", raising=False)
        monkeypatch.setenv("SPEAKER_ID_VOICEPRINTS_DIR", str(tmp_path))
        assert get_speaker_identifier(["Alice"]) is None

    def test_enabled_without_voiceprints_returns_none(self, monkeypatch, tmp_path):
        from backend.services.registry import get_speaker_identifier
        monkeypatch.setenv("SPEAKER_ID_ENABLED", "1")
        monkeypatch.setenv("SPEAKER_ID_MODEL", "/some/model.onnx")
        monkeypatch.setenv("SPEAKER_ID_VOICEPRINTS_DIR", str(tmp_path))  # empty dir
        assert get_speaker_identifier(["Alice"]) is None

    def test_enabled_with_model_and_prints_builds_identifier(self, monkeypatch, tmp_path):
        from backend.services.registry import get_speaker_identifier
        np.save(tmp_path / "Alice.npy", np.array([1.0, 0.0], np.float32))
        monkeypatch.setenv("SPEAKER_ID_ENABLED", "true")
        monkeypatch.setenv("SPEAKER_ID_MODEL", "/some/model.onnx")
        monkeypatch.setenv("SPEAKER_ID_VOICEPRINTS_DIR", str(tmp_path))
        monkeypatch.setenv("SPEAKER_ID_THRESHOLD", "0.6")
        ident = get_speaker_identifier(["Alice"])
        # Built without loading onnxruntime (no identify() call here).
        assert ident is not None
        assert ident.threshold == 0.6
        assert set(ident.voiceprints) == {"Alice"}

    def test_episode_speakers_match_but_role_annotated_guests_do_not(self, monkeypatch, tmp_path):
        """Guards the ep.guests pitfall (§5.3): prints are matched by bare name."""
        from backend.config import Episode
        from backend.services.registry import get_speaker_identifier
        np.save(tmp_path / "Sandra Maischberger.npy", np.array([1.0, 0.0], np.float32))
        np.save(tmp_path / "Julia Klöckner.npy", np.array([0.0, 1.0], np.float32))
        monkeypatch.setenv("SPEAKER_ID_ENABLED", "true")
        monkeypatch.setenv("SPEAKER_ID_MODEL", "/some/model.onnx")
        monkeypatch.setenv("SPEAKER_ID_VOICEPRINTS_DIR", str(tmp_path))
        ep = Episode(key="k", show="s", date="d", guests=[
            "Sandra Maischberger (Moderatorin)", "Julia Klöckner (CDU)", "Gregor Gysi (Linke)"])
        ident = get_speaker_identifier(ep.speakers)
        assert set(ident.voiceprints) == {"Sandra Maischberger", "Julia Klöckner"}
        assert get_speaker_identifier(ep.guests) is None
