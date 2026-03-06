"""
Reference Link Content Fetcher using Tavily Extract.

Pre-fetches reference link content once per episode so both claim extraction
and fact-checking receive the actual document text as show background.
"""

import asyncio
import logging
import os
import re

logger = logging.getLogger(__name__)

def clean_extracted_text(text: str) -> str:
    """Clean up markdown artifacts like images and links from scraped text."""
    if not text:
        return ""
    # Remove markdown images: ![alt](url)
    text = re.sub(r'!\[.*?\]\([^)]*\)', '', text)
    # Replace markdown links with just their text: [text](url) -> text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Reduce multiple blank lines to a maximum of two (one blank line)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

# Module-level cache: frozenset of URLs -> show_background string
_cache: dict[frozenset[str], str] = {}


def clear_cache():
    """Clear the reference content cache (useful for tests)."""
    _cache.clear()


async def fetch_show_background(urls: list[str]) -> str | None:
    """
    Fetch content from reference URLs using Tavily Extract and return as a
    single show-background text block.

    Results are cached by the set of URLs, so the same episode's links
    are only fetched once across audio blocks.

    Args:
        urls: List of reference URLs to fetch

    Returns:
        Combined extracted text as a single string, or None if no content available.
    """
    if not urls:
        return None

    cache_key = frozenset(urls)
    if cache_key in _cache:
        logger.info(f"Show background cache hit for {len(urls)} URLs")
        return _cache[cache_key]

    logger.info(f"Fetching show background for {len(urls)} URLs via Tavily Extract...")

    try:
        from tavily import TavilyClient

        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            logger.warning("TAVILY_API_KEY not set, skipping show background fetch")
            _cache[cache_key] = None
            return None

        client = TavilyClient(api_key=api_key)
        response = await asyncio.to_thread(client.extract, urls=urls)

        # Collect successfully extracted content
        sections: list[str] = []
        for item in response.get("results", []):
            raw_content = item.get("raw_content", "")
            if raw_content:
                cleaned_content = clean_extracted_text(raw_content)
                logger.info(f"Fetched {len(raw_content)} chars from {item.get('url', '?')}, cleaned to {len(cleaned_content)}")
                if cleaned_content:
                    sections.append(cleaned_content)

        if not sections:
            logger.warning("No content extracted from any reference URL")
            _cache[cache_key] = None
            return None

        result = "\n\n---\n\n".join(sections)
        _cache[cache_key] = result
        logger.info(f"Show background ready: {len(sections)}/{len(urls)} sources, {len(result)} chars total")
        return result

    except Exception:
        logger.exception("Failed to fetch show background")
        _cache[cache_key] = None
        return None
