"""
Web search tool for the fact-check agent.

Wraps tavily-python directly (PydanticAI tool). Restricts results to trusted
German domains and retries without the date filter when a date-filtered search
returns nothing — the behavior previously provided by FallbackSearchTool.
"""

import os
import logging

from tavily import AsyncTavilyClient

from .trusted_domains import TRUSTED_DOMAINS

logger = logging.getLogger(__name__)

_client: AsyncTavilyClient | None = None


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
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Search the web to verify a claim against trusted German sources.

    Args:
        query: The search query, in German.
        start_date: Optional earliest publication date, format YYYY-MM-DD.
        end_date: Optional latest publication date, format YYYY-MM-DD.
    """
    client = _get_client()
    kwargs: dict = {
        "search_depth": os.getenv("TAVILY_SEARCH_DEPTH", "basic"),
        "max_results": int(os.getenv("TAVILY_MAX_RESULTS", "5")),
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
