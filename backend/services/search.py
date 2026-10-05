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


async def tavily_extract(urls: list[str], query: str, chunks_per_source: int = 5) -> dict[str, str]:
    """Read deeper in documents already found (PDFs, studies): Tavily Extract returns, per
    URL, the passages most relevant to ``query`` (up to ``chunks_per_source`` of ≤500 chars).

    Returns ``{url: text}`` for the URLs that could be read. Costs 1 credit per 5 successful
    URLs (basic); failures are free.
    """
    if not urls:
        return {}
    result = await _get_client().extract(
        urls=urls, query=query, chunks_per_source=chunks_per_source,
        extract_depth="basic", format="text",
    )
    return {item.get("url"): item.get("raw_content") or ""
            for item in result.get("results", []) or [] if item.get("url")}
