"""
Voiceprint speaker identification for the live fast lane (ships behind SPEAKER_ID_ENABLED).

Identity is derived from the audio itself, independent of AssemblyAI's diarization: a
sherpa-onnx speaker embedding is matched (cosine, argmax) against the episode's enrolled
guests — a closed set — so a non-guest or an unclear segment falls below the gate and the
caller keeps its fallback speaker rather than getting a confident wrong name. See
``docs/speaker-id-integration-plan.md`` (§5.1); the offline spike lives in
``benchmarks/speaker_id_bench.py`` and shares the embed/cosine logic mirrored here.

This module is imported only when the feature is enabled, and it imports ``sherpa_onnx``
lazily inside ``_get_extractor`` — so a disabled flag never loads the ONNX stack. ``numpy``
is a light dependency (test + speakerid extras) and imports at module top. No ``soundfile``
in this prod path: live audio is already PCM (see ``pcm16_to_float32``); WAV reading stays
bench-only.
"""

from __future__ import annotations

import logging
import unicodedata
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# One ONNX extractor per (model_path, num_threads), built lazily and reused across
# sessions — loading the model is the only expensive step; embedding is cheap.
_extractor_cache: dict[tuple[str, int], object] = {}


def _get_extractor(model_path: str, num_threads: int):
    """Return a cached sherpa-onnx ``SpeakerEmbeddingExtractor`` (built on first use)."""
    key = (model_path, num_threads)
    extractor = _extractor_cache.get(key)
    if extractor is None:
        import sherpa_onnx  # lazy: only when we actually identify, never on a dark flag

        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=model_path, num_threads=num_threads, provider="cpu"
        )
        if not cfg.validate():
            raise ValueError(f"Invalid speaker-embedding model config for {model_path!r}")
        extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
        _extractor_cache[key] = extractor
    return extractor


def reset_speaker_cache() -> None:
    """Drop cached extractors. Used for test cleanup (see registry.reset_services)."""
    _extractor_cache.clear()


def _unit(vec: np.ndarray) -> np.ndarray:
    """L2-normalize to a unit vector; a zero vector is returned unchanged."""
    vec = np.asarray(vec, dtype=np.float32)
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else vec


def pcm16_to_float32(data: bytes) -> np.ndarray:
    """Little-endian PCM16 bytes → float32 samples in [-1, 1)."""
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def name_key(name: str) -> str:
    """Comparison key for speaker names: NFC + casefold.

    macOS may store "Dröge.npy" decomposed (o + combining umlaut) while the guest list is
    composed — without NFC they would silently never match.
    """
    return unicodedata.normalize("NFC", name).casefold()


def load_voiceprints(directory, names: list[str] | None = None) -> dict[str, np.ndarray]:
    """Load ``<Name>.npy`` unit voiceprints from ``directory``.

    Each file is L2-normalized on load. When ``names`` is given (the episode's guests),
    only matching prints are returned — case-insensitively — so classification is a closed
    set over this episode's speakers. A missing directory yields ``{}``.
    """
    root = Path(directory)
    if not root.is_dir():
        return {}
    wanted = {name_key(n) for n in names} if names else None
    prints: dict[str, np.ndarray] = {}
    for npy in sorted(root.glob("*.npy")):
        name = unicodedata.normalize("NFC", npy.stem)
        if wanted is not None and name_key(name) not in wanted:
            continue
        try:
            prints[name] = _unit(np.load(npy))
        except Exception:
            logger.exception("Failed to load voiceprint %s", npy)
    return prints


class SpeakerIdentifier:
    """Closed-set voiceprint classifier: PCM audio → ``(name|None, top_cosine)``.

    Collaborators can inject ``_embed_fn`` to bypass sherpa-onnx in unit tests; left unset,
    embeddings come from the cached ONNX extractor.
    """

    def __init__(
        self,
        model_path: str,
        voiceprints: dict[str, np.ndarray],
        *,
        threshold: float = 0.55,
        min_seconds: float = 1.5,
        num_threads: int = 1,
        sr: int = 16000,
        _embed_fn=None,
    ):
        self.model_path = model_path
        self.voiceprints = {name: _unit(vp) for name, vp in (voiceprints or {}).items()}
        self.threshold = threshold
        self.min_seconds = min_seconds
        self.num_threads = num_threads
        self.sr = sr
        self._embed_fn = _embed_fn

    def _embed(self, pcm_float32: np.ndarray, sr: int) -> np.ndarray:
        """One L2-normalized embedding for a PCM clip (mirrors the spike's ``embed``)."""
        if self._embed_fn is not None:
            return _unit(self._embed_fn(pcm_float32, sr))
        extractor = _get_extractor(self.model_path, self.num_threads)
        stream = extractor.create_stream()
        stream.accept_waveform(sr, pcm_float32)
        stream.input_finished()
        return _unit(np.asarray(extractor.compute(stream), dtype=np.float32))

    def identify(self, pcm_float32: np.ndarray, sr: int = 16000) -> tuple[str | None, float]:
        """Argmax the clip against enrolled prints, gated by ``threshold``/``min_seconds``.

        Returns ``(name, top1)`` when confident, else ``(None, top1)`` — never a name below
        the gate. Too-short audio or an empty print set short-circuits to ``(None, 0.0)``.
        """
        if not self.voiceprints:
            return None, 0.0
        if len(pcm_float32) / sr < self.min_seconds:
            return None, 0.0
        vec = self._embed(pcm_float32, sr)
        scores = {name: float(np.dot(vec, vp)) for name, vp in self.voiceprints.items()}
        best = max(scores, key=scores.get)
        top = scores[best]
        return (best, top) if top >= self.threshold else (None, top)
