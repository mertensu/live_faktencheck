"""
Logfire observability wiring.

Configured once at app startup. With send_to_logfire='if-token-present' it is a
silent no-op when no LOGFIRE_TOKEN is set, so it never becomes a hard runtime
dependency (e.g. on the VPS without a Logfire account).
"""

import logging

logger = logging.getLogger(__name__)

_configured = False


def configure_logfire() -> None:
    """Configure Logfire + PydanticAI instrumentation. Idempotent; safe without a token."""
    global _configured
    if _configured:
        return
    try:
        import logfire
    except ImportError:
        logger.warning("logfire not installed; observability disabled")
        _configured = True
        return

    logfire.configure(send_to_logfire="if-token-present", service_name="fact-check")
    logfire.instrument_pydantic_ai()
    _configured = True
    logger.info("Logfire configured (sends only when LOGFIRE_TOKEN is present)")
