"""
Tests for FastFactChecker (fast first-pass lane).

Covered:
- check_claim_async returns a structured FastVerdict dict (no self-critique fields set)
- speaker/original_claim fall back to the inputs when the model leaves them blank
- parallel Tavily searches are issued with the fast search_depth
- a search/model failure degrades to consistency "unklar" rather than raising
- _build_queries respects FAST_SEARCH_MAX_QUERIES
- reformulator queries are preferred over the heuristic variants, claim kept as safety net
"""

import pytest
from unittest.mock import AsyncMock, patch

from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from backend.services.fast_fact_checker import FastFactChecker, FastVerdict, Source

models.ALLOW_MODEL_REQUESTS = False


FAKE_SEARCH = {
    "results": [
        {"title": "Statistisches Bundesamt", "url": "https://destatis.de/x", "content": "Zahlen ..."},
        {"title": "Bundesbank", "url": "https://bundesbank.de/y", "content": "Weitere Daten ..."},
    ]
}

MOCK_VERDICT = FastVerdict(
    speaker="",
    original_claim="",
    consistency="hoch",
    evidence="Die offiziellen Zahlen stützen die Behauptung.",
    sources=[Source(url="https://destatis.de/x", title="Statistisches Bundesamt")],
)


def _make_checker():
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-api-key", "TAVILY_API_KEY": "test-tavily-key"}):
        return FastFactChecker()


@pytest.fixture
def checker():
    c = _make_checker()
    with c.agent.override(model=TestModel(custom_output_args=MOCK_VERDICT.model_dump())):
        yield c


class TestFastCheck:
    async def test_returns_structured_verdict(self, checker):
        with patch("backend.services.fast_fact_checker.tavily_search", AsyncMock(return_value=FAKE_SEARCH)):
            result = await checker.check_claim_async(
                speaker="Angela Merkel", claim="Deutschland hat 83 Millionen Einwohner."
            )
        assert isinstance(result, dict)
        assert result["consistency"] == "hoch"
        assert isinstance(result["evidence"], str) and result["evidence"]
        assert isinstance(result["sources"], list)
        # Fast lane never self-critiques.
        assert result["double_check"] is False
        assert result["critique_note"] == ""

    async def test_speaker_and_claim_fallback(self, checker):
        """Model returned blank speaker/original_claim -> filled from inputs."""
        with patch("backend.services.fast_fact_checker.tavily_search", AsyncMock(return_value=FAKE_SEARCH)):
            result = await checker.check_claim_async(speaker="Olaf Scholz", claim="Die Inflation sinkt.")
        assert result["speaker"] == "Olaf Scholz"
        assert result["original_claim"] == "Die Inflation sinkt."

    async def test_parallel_searches_use_fast_depth(self, checker):
        mock_search = AsyncMock(return_value=FAKE_SEARCH)
        with patch("backend.services.fast_fact_checker.tavily_search", mock_search):
            await checker.check_claim_async(speaker="X", claim="Behauptung Y.")
        # Without reformulator queries: one search per heuristic variant (3), each with
        # the fast lane's depth override.
        assert mock_search.call_count == 3
        for call in mock_search.call_args_list:
            assert call.kwargs.get("search_depth") == checker.search_depth

    async def test_search_failure_degrades_to_unklar(self, checker):
        with patch("backend.services.fast_fact_checker.tavily_search", AsyncMock(side_effect=RuntimeError("boom"))):
            result = await checker.check_claim_async(speaker="X", claim="Behauptung Z.")
        # Searches swallow their own errors -> empty evidence, but the synthesis
        # (mocked) still returns a verdict; the call must never raise.
        assert result["consistency"] in {"hoch", "niedrig", "unklar", "keine Datenlage"}

    async def test_synthesis_failure_degrades_to_unklar(self):
        """If the synthesis agent itself raises, return an 'unklar' fallback dict."""
        c = _make_checker()
        with patch("backend.services.fast_fact_checker.tavily_search", AsyncMock(return_value=FAKE_SEARCH)):
            with patch.object(c.agent, "run", AsyncMock(side_effect=RuntimeError("model down"))):
                result = await c.check_claim_async(speaker="X", claim="Behauptung.")
        assert result["consistency"] == "unklar"
        assert "Fehler" in result["evidence"]

    def test_build_queries_respects_cap(self):
        with patch.dict("os.environ", {
            "GEMINI_API_KEY": "k", "TAVILY_API_KEY": "k", "FAST_SEARCH_MAX_QUERIES": "1",
        }):
            c = FastFactChecker()
        assert c._build_queries("eine Behauptung") == ["eine Behauptung"]

    def test_build_queries_prefers_given_queries(self, checker):
        qs = checker._build_queries("Die Behauptung.", ["Arbeitslosenquote 2026", "BA Arbeitsmarkt"])
        assert qs == ["Arbeitslosenquote 2026", "BA Arbeitsmarkt", "Die Behauptung."]

    def test_build_queries_dedupes_and_caps(self, checker):
        given = ["a b", "A B", "c d", "e f", "g h", "i j", ""]
        qs = checker._build_queries("claim", given)
        assert qs == ["a b", "c d", "e f", "g h", "i j"][: checker.max_queries]

    def test_build_queries_falls_back_without_queries(self, checker):
        assert len(checker._build_queries("claim", [])) == 3
        assert checker._build_queries("claim", None)[0] == "claim"

    async def test_given_queries_are_searched(self, checker):
        mock_search = AsyncMock(return_value=FAKE_SEARCH)
        with patch("backend.services.fast_fact_checker.tavily_search", mock_search):
            await checker.check_claim_async(speaker="X", claim="Behauptung Y.", queries=["q1", "q2"])
        searched = [c.args[0] for c in mock_search.call_args_list]
        assert searched == ["q1", "q2", "Behauptung Y."]

    async def test_results_sorted_official_first_and_labelled(self, checker):
        mixed = {"results": [
            {"title": "Handelsblatt", "url": "https://www.handelsblatt.com/a", "content": "x"},
            {"title": "Linke", "url": "https://www.die-linke.de/b", "content": "x"},
            {"title": "DIW", "url": "https://www.diw.de/c", "content": "x"},
            {"title": "Destatis", "url": "https://www.destatis.de/d", "content": "x"},
        ]}
        with patch("backend.services.fast_fact_checker.tavily_search", AsyncMock(return_value=mixed)):
            results = await checker._gather_evidence("claim", ["q"])
        assert [r["title"] for r in results] == ["Destatis", "DIW", "Handelsblatt", "Linke"]
        text = checker._format_evidence(results)
        assert "[amtlich] Destatis" in text and "[Presse] Handelsblatt" in text and "[Partei] Linke" in text

    async def test_sources_not_in_results_are_dropped(self):
        c = _make_checker()
        verdict = MOCK_VERDICT.model_copy(update={"sources": [
            Source(url="https://destatis.de/x", title="Statistisches Bundesamt"),
            Source(url="https://destatis.de/erfunden", title="Erfunden"),
        ]})
        with c.agent.override(model=TestModel(custom_output_args=verdict.model_dump())):
            with patch("backend.services.fast_fact_checker.tavily_search", AsyncMock(return_value=FAKE_SEARCH)):
                result = await c.check_claim_async(speaker="X", claim="Behauptung.")
        assert [s["url"] for s in result["sources"]] == ["https://destatis.de/x"]


class TestSourceTier:
    def test_tiers(self):
        from backend.services.trusted_domains import source_tier
        assert source_tier("https://www.destatis.de/DE/x.html") == (0, "amtlich")
        assert source_tier("https://ec.europa.eu/eurostat/web/x") == (0, "amtlich")
        assert source_tier("https://www.iwkoeln.de/x") == (1, "Forschung")
        assert source_tier("https://um.baden-wuerttemberg.de/x") == (2, "Land")
        assert source_tier("https://www.statistik-bw.de/x") == (2, "Land")
        assert source_tier("https://www.zeit.de/x") == (3, "Presse")
        assert source_tier("https://afd.de/x") == (4, "Partei")
        assert source_tier("https://example.org/x")[0] == 3
        assert source_tier("")[0] == 3

    async def test_homepages_and_plenary_transcripts_dropped(self, checker):
        hits = {"results": [
            {"title": "Bremen", "url": "https://umwelt.bremen.de", "content": "x"},
            {"title": "HB", "url": "https://www.handelsblatt.com/", "content": "x"},
            {"title": "TH", "url": "https://www.thueringer-landtag.de/uploads/tx_tltcalendar/protocols/A120.pdf", "content": "x"},
            {"title": "RLP", "url": "https://dokumente.landtag.rlp.de/landtag/plenarprotokolle/24-P-18.pdf", "content": "x"},
            {"title": "RLP2", "url": "https://dokumente.landtag.rlp.de/x/PLPR-Sitzung-15-039.pdf", "content": "x"},
            {"title": "BT", "url": "https://dserver.bundestag.de/btp/20/20123.pdf", "content": "x"},
            {"title": "LSA", "url": "https://www.landtag.sachsen-anhalt.de/50-sitzungsperiode?transcriptSessions=lsaSessionsAjax", "content": "x"},
            {"title": "Drucksache", "url": "https://dserver.bundestag.de/btd/19/134/1913440.pdf", "content": "x"},
            {"title": "BW", "url": "https://um.baden-wuerttemberg.de/de/energiepreise", "content": "x"},
        ]}
        with patch("backend.services.fast_fact_checker.tavily_search", AsyncMock(return_value=hits)):
            results = await checker._gather_evidence("claim", ["q"])
        assert [r["title"] for r in results] == ["Drucksache", "BW"]

    async def test_duplicate_pages_collapse(self, checker):
        dupes = {"results": [
            {"title": "A", "url": "https://www.destatis.de/DE/PD25_183.htm", "content": "x"},
            {"title": "B", "url": "https://www.destatis.de/DE/PD25_183.html", "content": "x"},
            {"title": "C", "url": "http://destatis.de/DE/PD25_183.html?nn=2110", "content": "x"},
            {"title": "D", "url": "https://www.destatis.de/DE/andere.html", "content": "x"},
        ]}
        with patch("backend.services.fast_fact_checker.tavily_search", AsyncMock(return_value=dupes)):
            results = await checker._gather_evidence("claim", ["q"])
        assert [r["title"] for r in results] == ["A", "D"]
