"""
Web search tool for the fact-check agent.

Wraps tavily-python directly (PydanticAI tool). Restricts results to trusted
German domains and retries without the date filter when a date-filtered search
returns nothing — the behavior previously provided by FallbackSearchTool.
"""

import os
import logging
from typing import Literal

from tavily import AsyncTavilyClient

from .trusted_domains import TRUSTED_DOMAINS

logger = logging.getLogger(__name__)

_client: AsyncTavilyClient | None = None

# Lightweight observability: how often each depth was actually used. Handy for
# benchmarks and for monitoring how often the agent escalates to "advanced".
SEARCH_DEPTH_COUNTS: dict[str, int] = {}


def _get_client() -> AsyncTavilyClient:
    global _client
    if _client is None:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise ValueError("TAVILY_API_KEY environment variable not set")
        _client = AsyncTavilyClient(api_key=api_key)
    return _client


async def tavily_search(
    query: str,
    depth: Literal["fast", "advanced"] = "fast",
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Search the web to verify a claim against trusted German sources.

    Args:
        query: The search query, in German.
        depth: Search depth, chosen per query:
            "fast"     — quick sub-second overview. Use this FIRST for every claim.
            "advanced" — slower, thorough deep-dive. Only escalate to this when the
                         fast pass is inconclusive, contradictory, or the claim
                         hinges on precise figures, dates, or an authoritative source.
        start_date: Optional earliest publication date, format YYYY-MM-DD.
        end_date: Optional latest publication date, format YYYY-MM-DD.
    """
    client = _get_client()
    # An explicit TAVILY_SEARCH_DEPTH env pins the depth (overriding the agent's
    # choice) — used to force a fixed depth for benchmarks or as a kill-switch.
    effective_depth = os.getenv("TAVILY_SEARCH_DEPTH") or depth
    SEARCH_DEPTH_COUNTS[effective_depth] = SEARCH_DEPTH_COUNTS.get(effective_depth, 0) + 1
    max_results_env = os.getenv("TAVILY_MAX_RESULTS")
    kwargs: dict = {
        "search_depth": effective_depth,
        "max_results": int(max_results_env) if max_results_env else 5,
        "include_domains": TRUSTED_DOMAINS,
    }
    if start_date:
        kwargs["start_date"] = start_date
    if end_date:
        kwargs["end_date"] = end_date

    result = await client.search(query, **kwargs)

    if not result.get("results") and (start_date or end_date):
        logger.info("Empty results with date filter — retrying without date filter: '%s'", query)
        kwargs.pop("start_date", None)
        kwargs.pop("end_date", None)
        result = await client.search(query, **kwargs)

    return result
