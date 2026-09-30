"""
Web search for the fast fact checker.

Wraps tavily-python directly and restricts results to trusted German domains.
"""

import os

from tavily import AsyncTavilyClient

from .trusted_domains import TRUSTED_DOMAINS


_client: AsyncTavilyClient | None = None


def _get_client() -> AsyncTavilyClient:
    global _client
    if _client is None:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise ValueError("TAVILY_API_KEY environment variable not set")
        _client = AsyncTavilyClient(api_key=api_key)
    return _client


async def tavily_search(query: str, search_depth: str = "basic") -> dict:
    """Search the web to verify a claim against trusted German sources.

    Args:
        query: The search query, in German.
        search_depth: Tavily tier ("fast"/"basic"/"advanced").
    """
    client = _get_client()
    return await client.search(
        query,
        search_depth=search_depth,
        max_results=int(os.getenv("TAVILY_MAX_RESULTS", "5")),
        include_domains=TRUSTED_DOMAINS,
    )
