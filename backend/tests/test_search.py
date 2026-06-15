"""Tests for the tavily_search PydanticAI tool."""

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


async def test_search_retries_without_date_filter_on_empty(mock_tavily):
    from backend.services.search import tavily_search
    # First call (with date filter) empty, second call (no filter) has results.
    mock_tavily.search.side_effect = [
        {"results": []},
        {"results": [{"title": "t", "url": "u"}]},
    ]

    result = await tavily_search("Mindestlohn", start_date="2024-01-01")

    assert result["results"][0]["url"] == "u"
    assert mock_tavily.search.await_count == 2
    # Second call must NOT carry the date filter.
    second_kwargs = mock_tavily.search.await_args_list[1].kwargs
    assert "start_date" not in second_kwargs


async def test_search_no_retry_when_no_date_filter(mock_tavily):
    from backend.services.search import tavily_search
    mock_tavily.search.return_value = {"results": []}

    result = await tavily_search("Mindestlohn")

    assert result["results"] == []
    assert mock_tavily.search.await_count == 1
