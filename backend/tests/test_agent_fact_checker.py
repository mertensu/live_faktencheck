"""
Tests for AgentFactChecker (LIVE_CHECKER=agent).

Covered:
- one research round of parallel searches, then a verdict dict like the fast check's,
  with the searches it sent
- sources: only URLs the tools returned, never press; press hits carry no URL or title
- searches after the allowed round(s) are refused
- too few searches: sent back once for more; a text naming the press: sent back once
- a failure degrades to "unklar"
- the registry picks the agent checker with LIVE_CHECKER=agent
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from backend.services.agent_fact_checker import AgentFactChecker

models.ALLOW_MODEL_REQUESTS = False

TRUSTED = {"results": [
    {"title": "Destatis", "url": "https://www.destatis.de/a", "content": "83,6 Mio. Einwohner 2025."},
    {"title": "BiB", "url": "https://www.bib.bund.de/b", "content": "Bevölkerung wächst durch Zuwanderung."},
]}
PRESS = {"results": [{"title": "Artikel", "url": "https://www.spiegel.de/c", "content": "Laut Destatis 83 Mio."}]}

VERDICT = {"consistency": "hoch", "evidence": "Laut Destatis lebten 2025 rund 83,6 Mio. Menschen in Deutschland.",
           "sources": [{"url": "https://www.destatis.de/a", "title": "Destatis"},
                       {"url": "https://www.spiegel.de/c", "title": "Spiegel"},
                       {"url": "https://erfunden.de/x", "title": "Erfunden"}]}


async def fake_search(query, search_depth="basic", include_domains=None):
    return PRESS if include_domains and "spiegel.de" in include_domains else TRUSTED


def _model(rounds, final=VERDICT, seen=None):
    """Each round: the tool calls of one response; then the final JSON verdict."""
    calls = {"n": 0}

    def respond(messages, info: AgentInfo) -> ModelResponse:
        if seen is not None:
            seen.extend(p for m in messages for p in getattr(m, "parts", []) if isinstance(p, ToolReturnPart))
        i = calls["n"]
        calls["n"] += 1
        if i < len(rounds):
            return ModelResponse(parts=[ToolCallPart(tool, {"query": q}) for tool, q in rounds[i]])
        out = final(i) if callable(final) else final
        return ModelResponse(parts=[TextPart(json.dumps(out, ensure_ascii=False))])

    return FunctionModel(respond)


@pytest.fixture
def checker():
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test", "TAVILY_API_KEY": "test", "REQUESTY_API_KEY": ""}):
        return AgentFactChecker()


THREE = [("suche", "Einwohner Deutschland 2025"), ("suche", "Bevölkerungsstand Destatis"),
         ("presse_hinweis", "83 Millionen Einwohner")]


async def test_one_round_then_verdict(checker):
    search = AsyncMock(side_effect=fake_search)
    with patch("backend.services.agent_fact_checker.tavily_search", search), \
            checker.agent.override(model=_model([THREE])):
        result = await checker.check_claim_async("Julia", "Deutschland hat 83 Mio. Einwohner.",
                                                 episode_date="19. September 2025")
    assert search.await_count == 3
    assert result["search_queries"] == ["Einwohner Deutschland 2025", "Bevölkerungsstand Destatis",
                                        "[presse] 83 Millionen Einwohner"]
    assert result["consistency"] == "hoch"
    assert result["speaker"] == "Julia" and result["original_claim"] == "Deutschland hat 83 Mio. Einwohner."
    assert result["double_check"] is False and result["critique_note"] == ""
    # Press and invented URLs are dropped.
    assert [s["url"] for s in result["sources"]] == ["https://www.destatis.de/a"]


async def test_press_hits_come_without_url_or_title(checker):
    seen = []
    with patch("backend.services.agent_fact_checker.tavily_search", AsyncMock(side_effect=fake_search)), \
            checker.agent.override(model=_model([THREE], seen=seen)):
        await checker.check_claim_async("Julia", "Behauptung.")
    press = [p.content for p in seen if p.tool_name == "presse_hinweis"]
    assert press and all("spiegel" not in c and "Artikel" not in c and c.startswith("[Hinweis]") for c in press)
    trusted = [p.content for p in seen if p.tool_name == "suche"]
    assert all("https://www.destatis.de/a" in c and "[amtlich]" in c for c in trusted)


async def test_searches_after_the_round_are_refused(checker):
    search = AsyncMock(side_effect=fake_search)
    second = [("suche", "noch eine Suche")]
    with patch("backend.services.agent_fact_checker.tavily_search", search), \
            checker.agent.override(model=_model([THREE, second])):
        await checker.check_claim_async("Julia", "Behauptung.")
    assert search.await_count == 3


async def test_too_few_searches_are_sent_back_once(checker):
    search = AsyncMock(side_effect=fake_search)
    # One search, a verdict (refused: too few), two more searches, the verdict.
    calls = {"n": 0}

    def respond(messages, info):
        i = calls["n"]
        calls["n"] += 1
        if i == 0:
            return ModelResponse(parts=[ToolCallPart("suche", {"query": "eine Suche"})])
        if i == 2:
            return ModelResponse(parts=[ToolCallPart("suche", {"query": "zwei"}), ToolCallPart("suche", {"query": "drei"})])
        return ModelResponse(parts=[TextPart(json.dumps(VERDICT, ensure_ascii=False))])

    with patch("backend.services.agent_fact_checker.tavily_search", search), \
            checker.agent.override(model=FunctionModel(respond)):
        result = await checker.check_claim_async("Julia", "Behauptung.")
    assert search.await_count == 3
    assert result["consistency"] == "hoch"


async def test_text_naming_the_press_is_sent_back_once(checker):
    named = {**VERDICT, "evidence": "Laut Spiegel lebten 83 Mio. Menschen in Deutschland."}
    texts = []

    def final(i):
        out = named if not texts else VERDICT
        texts.append(out["evidence"])
        return out

    with patch("backend.services.agent_fact_checker.tavily_search", AsyncMock(side_effect=fake_search)), \
            checker.agent.override(model=_model([THREE], final=final)):
        result = await checker.check_claim_async("Julia", "Behauptung.")
    assert len(texts) == 2
    assert "Spiegel" not in result["evidence"]


async def test_failure_degrades_to_unklar(checker):
    def boom(messages, info):
        raise RuntimeError("kaputt")

    with checker.agent.override(model=FunctionModel(boom)):
        result = await checker.check_claim_async("Julia", "Behauptung.")
    assert result["consistency"] == "unklar"
    assert "kaputt" in result["evidence"] and result["sources"] == []


def test_registry_picks_agent_checker():
    from backend.services import registry
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test", "LIVE_CHECKER": "agent", "REQUESTY_API_KEY": ""}):
        registry.reset_services()
        assert registry.get_fast_fact_checker().check_depth == "agent"
        registry.reset_services()
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test", "LIVE_CHECKER": "fast", "REQUESTY_API_KEY": ""}):
        assert registry.get_fast_fact_checker().check_depth == "fast"
        registry.reset_services()
