"""
Claim gate — the seam that decides whether a window of streamed text contains a
check-worthy claim (and extracts it).

The default implementation wraps the flash-lite window agent on ``ClaimExtractor``.
It is deliberately a thin protocol so a cheaper pre-filter (e.g. a Jev decision model)
can be dropped in later without touching the streaming layer.
"""

import logging
from typing import List, Protocol, runtime_checkable

from .claim_extraction import ExtractedClaim, ClaimExtractor

logger = logging.getLogger(__name__)


@runtime_checkable
class ClaimGate(Protocol):
    """Given a short text window, return check-worthy claims (empty if none)."""

    async def gate(
        self,
        window_text: str,
        guests: list[str],
        context: str = "",
        conversation_type: str = "",
        excluded_speakers: list[str] | None = None,
        previous_context: str | None = None,
    ) -> List[ExtractedClaim]: ...


class ExtractorGate:
    """Default ``ClaimGate``: runs the extractor's flash-lite window agent."""

    def __init__(self, extractor: ClaimExtractor):
        self._extractor = extractor

    async def gate(
        self,
        window_text: str,
        guests: list[str],
        context: str = "",
        conversation_type: str = "",
        excluded_speakers: list[str] | None = None,
        previous_context: str | None = None,
    ) -> List[ExtractedClaim]:
        return await self._extractor.extract_window_async(
            window_text,
            guests,
            context=context,
            conversation_type=conversation_type,
            excluded_speakers=excluded_speakers,
            previous_context=previous_context,
        )
