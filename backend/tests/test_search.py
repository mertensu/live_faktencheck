"""Tests for the tavily_search wrapper."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_tavily(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    # Reset the cached client so each test gets a fresh mock.
    import backend.services.search as search_mod
    search_mod._client = None
    with patch("backend.services.search.AsyncTavilyClient") as cls:
        instance = cls.return_value
        instance.search = AsyncMock()
        yield instance


async def test_search_returns_results(mock_tavily):
    from backend.services.search import tavily_search
    mock_tavily.search.return_value = {"results": [{"title": "t", "url": "u"}]}

    result = await tavily_search("Mindestlohn 2024")

    assert result["results"][0]["url"] == "u"
    mock_tavily.search.assert_awaited_once()


async def test_search_passes_depth_and_trusted_domains(mock_tavily):
    from backend.services.search import tavily_search
    from backend.services.trusted_domains import TRUSTED_DOMAINS
    mock_tavily.search.return_value = {"results": []}

    await tavily_search("Mindestlohn", search_depth="advanced")

    kwargs = mock_tavily.search.await_args.kwargs
    assert kwargs["search_depth"] == "advanced"
    assert kwargs["include_domains"] == TRUSTED_DOMAINS
    assert mock_tavily.search.await_count == 1


async def test_extract_returns_text_per_readable_url(mock_tavily):
    from backend.services.search import tavily_extract
    mock_tavily.extract = AsyncMock(return_value={
        "results": [{"url": "https://x.de/a.pdf", "raw_content": "Ausgaben 8,8 Mrd."}],
        "failed_results": [{"url": "https://x.de/b.pdf"}],
    })

    out = await tavily_extract(["https://x.de/a.pdf", "https://x.de/b.pdf"], query="6 Mrd.")

    assert out == {"https://x.de/a.pdf": "Ausgaben 8,8 Mrd."}
    kwargs = mock_tavily.extract.await_args.kwargs
    assert kwargs["query"] == "6 Mrd." and kwargs["extract_depth"] == "basic"


async def test_extract_without_urls_makes_no_call(mock_tavily):
    from backend.services.search import tavily_extract
    mock_tavily.extract = AsyncMock()
    assert await tavily_extract([], query="x") == {}
    mock_tavily.extract.assert_not_awaited()
