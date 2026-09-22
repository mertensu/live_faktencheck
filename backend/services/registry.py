"""
Service registry for lazy-loaded singleton services.

Provides centralized access to AI services to avoid duplicate instances
across different routers.
"""

import logging
import os

logger = logging.getLogger(__name__)

_transcription_service = None
_claim_extractor = None
_fact_checker = None
_fast_fact_checker = None


def get_transcription_service():
    """Get or create the TranscriptionService singleton."""
    global _transcription_service
    if _transcription_service is None:
        from backend.services.transcription import TranscriptionService
        _transcription_service = TranscriptionService()
    return _transcription_service


def get_claim_extractor():
    """Get or create the ClaimExtractor singleton."""
    global _claim_extractor
    if _claim_extractor is None:
        from backend.services.claim_extraction import ClaimExtractor
        _claim_extractor = ClaimExtractor()
    return _claim_extractor


def get_fact_checker():
    """Get or create the FactChecker singleton."""
    global _fact_checker
    if _fact_checker is None:
        from backend.services.fact_checker import FactChecker
        _fact_checker = FactChecker()
    return _fact_checker


def get_fast_fact_checker():
    """Get or create the FastFactChecker singleton (live fast lane)."""
    global _fast_fact_checker
    if _fast_fact_checker is None:
        from backend.services.fast_fact_checker import FastFactChecker
        _fast_fact_checker = FastFactChecker()
    return _fast_fact_checker


def get_speaker_identifier(guests=None):
    """Build a voiceprint SpeakerIdentifier for this episode's guests, or None.

    Ships dark: returns None unless ``SPEAKER_ID_ENABLED`` is truthy. Also returns None
    (with a warning) when the model path or the guest-filtered voiceprint set is missing,
    so the caller cleanly falls back to diarization/LLM speakers. Not a singleton — it is
    parameterized by ``guests`` — but the heavy ONNX extractor is process-cached inside
    speaker_id, so repeated calls are cheap.
    """
    if os.getenv("SPEAKER_ID_ENABLED", "false").lower() not in ("1", "true", "yes"):
        return None

    from backend.services.speaker_id import SpeakerIdentifier, load_voiceprints

    model = os.getenv("SPEAKER_ID_MODEL")
    vp_dir = os.getenv("SPEAKER_ID_VOICEPRINTS_DIR", "backend/data/voiceprints")
    prints = load_voiceprints(vp_dir, guests)
    if not model or not prints:
        logger.warning(
            "SPEAKER_ID_ENABLED but %s — speaker identification disabled for this session",
            "SPEAKER_ID_MODEL is unset" if not model else f"no voiceprints in {vp_dir}",
        )
        return None
    return SpeakerIdentifier(
        model, prints,
        threshold=float(os.getenv("SPEAKER_ID_THRESHOLD", "0.55")),
        min_seconds=float(os.getenv("SPEAKER_ID_MIN_SECONDS", "1.5")),
        num_threads=int(os.getenv("SPEAKER_ID_NUM_THREADS", "1")),
    )


def reset_services():
    """Reset all service instances. Used for test cleanup."""
    global _transcription_service, _claim_extractor, _fact_checker, _fast_fact_checker
    _transcription_service = None
    _claim_extractor = None
    _fact_checker = None
    _fast_fact_checker = None
    from backend.services.speaker_id import reset_speaker_cache
    reset_speaker_cache()
