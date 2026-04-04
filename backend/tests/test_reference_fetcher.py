"""Tests for the show background fetcher."""

import pytest
from unittest.mock import patch, MagicMock

from backend.services.reference_fetcher import fetch_show_background, clear_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear cache before each test."""
    clear_cache()
    yield
    clear_cache()


@pytest.mark.asyncio
async def test_empty_urls_returns_none():
    result = await fetch_show_background([])
    assert result is None


@pytest.mark.asyncio
async def test_fetch_returns_combined_content():
    mock_client = MagicMock()
    mock_client.extract.return_value = {
        "results": [
            {"url": "https://example.com/law", "raw_content": "Law text here"},
            {"url": "https://example.com/report", "raw_content": "Report text here"},
        ]
    }

    with patch.dict("os.environ", {"TAVILY_API_KEY": "fake-key"}), \
         patch("tavily.TavilyClient", return_value=mock_client):
        result = await fetch_show_background(
            ["https://example.com/law", "https://example.com/report"]
        )

    assert "Law text here" in result
    assert "Report text here" in result
    assert "---" in result  # separator between sections


@pytest.mark.asyncio
async def test_no_content_extracted_returns_none():
    mock_client = MagicMock()
    mock_client.extract.return_value = {"results": []}

    with patch.dict("os.environ", {"TAVILY_API_KEY": "fake-key"}), \
         patch("tavily.TavilyClient", return_value=mock_client):
        result = await fetch_show_background(["https://example.com/missing"])

    assert result is None


@pytest.mark.asyncio
async def test_cache_prevents_refetch():
    mock_client = MagicMock()
    mock_client.extract.return_value = {
        "results": [{"url": "https://example.com/a", "raw_content": "Content A"}]
    }

    urls = ["https://example.com/a"]

    with patch.dict("os.environ", {"TAVILY_API_KEY": "fake-key"}), \
         patch("tavily.TavilyClient", return_value=mock_client):
        result1 = await fetch_show_background(urls)
        result2 = await fetch_show_background(urls)

    assert result1 == result2
    mock_client.extract.assert_called_once()


@pytest.mark.asyncio
async def test_no_api_key_returns_none():
    with patch.dict("os.environ", {}, clear=True):
        result = await fetch_show_background(["https://example.com/a"])

    assert result is None


@pytest.mark.asyncio
async def test_exception_returns_none():
    mock_client = MagicMock()
    mock_client.extract.side_effect = RuntimeError("API error")

    with patch.dict("os.environ", {"TAVILY_API_KEY": "fake-key"}), \
         patch("tavily.TavilyClient", return_value=mock_client):
        result = await fetch_show_background(["https://example.com/a"])

    assert result is None
