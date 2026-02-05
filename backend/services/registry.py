"""
Service registry for lazy-loaded singleton services.

Provides centralized access to AI services to avoid duplicate instances
across different routers.
"""

_transcription_service = None
_claim_extractor = None
_fact_checker = None


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


def reset_services():
    """Reset all service instances. Used for test cleanup."""
    global _transcription_service, _claim_extractor, _fact_checker
    _transcription_service = None
    _claim_extractor = None
    _fact_checker = None
