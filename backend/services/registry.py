"""
Service registry for lazy-loaded singleton services.

Provides centralized access to AI services to avoid duplicate instances
across different routers.
"""

_claim_extractor = None
_fast_fact_checker = None


def get_claim_extractor():
    """Get or create the ClaimExtractor singleton."""
    global _claim_extractor
    if _claim_extractor is None:
        from backend.services.claim_extraction import ClaimExtractor
        _claim_extractor = ClaimExtractor()
    return _claim_extractor


def get_fast_fact_checker():
    """Get or create the FastFactChecker singleton (live fast lane)."""
    global _fast_fact_checker
    if _fast_fact_checker is None:
        from backend.services.fast_fact_checker import FastFactChecker
        _fast_fact_checker = FastFactChecker()
    return _fast_fact_checker


def reset_services():
    """Reset all service instances. Used for test cleanup."""
    global _claim_extractor, _fast_fact_checker
    _claim_extractor = None
    _fast_fact_checker = None
