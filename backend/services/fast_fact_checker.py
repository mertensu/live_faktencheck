"""
Fast Fact Checker — first-pass verdict for the live streaming lane.

Unlike ``FactChecker`` (a ReAct agent that loops search→reason up to ~35 times and
then self-critiques), this service is built for latency: it fires a few Tavily
searches *in parallel* (queries written by the reformulator, else heuristic variants),
then makes a single synthesis call that returns only a ``consistency`` level
(Vertrauenslevel) and one or two short sentences. No agent loop, no
self-critique. A claim can later be upgraded to a full verdict by the deep
``FactChecker`` (see check_depth="fast" rows).
"""

import os
import re
import asyncio
import logging
from typing import List, Dict, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from backend.utils import load_prompt
from backend.lang import (
    SOURCE_URL_DESCRIPTION,
    SOURCE_TITLE_DESCRIPTION,
    CONSISTENCY_DESCRIPTION,
    SOURCES_DESCRIPTION,
)
from .llm_base import build_model, settings_with_thinking
from .search import tavily_search
from .trusted_domains import source_tier
from pydantic_ai import Agent

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.6-flash"


def _url_key(url: str) -> str:
    """Dedup key: the same page often comes back as http/https, with/without www,
    .htm/.html or with tracking query params (e.g. Destatis' ``?nn=2110``)."""
    u = urlparse(url.strip())
    host = u.netloc.lower().removeprefix("www.")
    path = u.path.rstrip("/")
    if path.endswith(".htm"):
        path += "l"
    return f"{host}{path}" if host else url.strip()


# Plenary transcripts (Bundestag /btp/, Landtage) are speeches, not evidence.
_PLENARY_RE = re.compile(r"plenarprotokoll|/protocols/|/btp/|plpr|transcript", re.IGNORECASE)


def _is_noise(url: str) -> bool:
    """Hits that carry no checkable content: bare homepages and plenary transcripts."""
    u = urlparse(url.strip())
    if u.netloc and u.path.strip("/") == "" and not u.query:
        return True
    return bool(_PLENARY_RE.search(f"{u.path}?{u.query}"))


class Source(BaseModel):
    url: str = Field(description=SOURCE_URL_DESCRIPTION)
    title: str = Field(description=SOURCE_TITLE_DESCRIPTION)


class FastVerdict(BaseModel):
    """A fast first-pass verdict. Field names mirror ``FactCheckResponse`` so the
    same ``build_fact_check_dict`` mapping stores it unchanged."""
    speaker: str = ""
    original_claim: str = ""
    # evidence before consistency: the model writes the finding first and derives the
    # level from it, instead of committing to a level and justifying it afterwards.
    evidence: str = Field(
        description="Kurze deutschsprachige Einschätzung (ein, höchstens zwei Sätze) mit "
                    "der entscheidenden Zahl und ihrer Quelle."
    )
    consistency: Literal["hoch", "niedrig", "unklar", "keine Datenlage"] = Field(
        description=CONSISTENCY_DESCRIPTION
    )
    sources: List[Source] = Field(default_factory=list, description=SOURCES_DESCRIPTION)


class FastFactChecker:
    """Fast, loop-free fact-check: parallel Tavily searches + one synthesis call."""

    def __init__(self):
        self.model_name = os.getenv("GEMINI_MODEL_FAST_CHECK", DEFAULT_MODEL)
        self.fallback_model_name = os.getenv("GEMINI_MODEL_FACT_CHECKER_FALLBACK", "gemini-3-flash-preview")
        self.max_queries = int(os.getenv("FAST_SEARCH_MAX_QUERIES", "5"))
        # Own Tavily tier, independent of the deep checker's TAVILY_SEARCH_DEPTH. The
        # searches run in parallel, so basic costs ~one search's latency, not five.
        self.search_depth = os.getenv("FAST_TAVILY_SEARCH_DEPTH", "basic")
        # The deciding number often sits past the first few hundred characters.
        self.snippet_chars = int(os.getenv("FAST_SNIPPET_CHARS", "1200"))

        # Thinking dominates the synthesis latency; "low" cut it from ~7.7 s to ~2.8 s
        # without losing accuracy (benchmarks/fast_check_ab.py).
        self.thinking_level = os.getenv("GEMINI_THINKING_FAST_CHECK", "low")

        self.prompt_template = load_prompt("fast_fact_checker.md")

        # No tools: we run the searches ourselves and hand the results to the agent.
        self.agent = Agent(
            build_model(self.model_name, self.fallback_model_name),
            output_type=FastVerdict,
            instructions=self.prompt_template,
            model_settings=settings_with_thinking(self.thinking_level),
            retries=1,
        )

        logger.info(
            f"FastFactChecker initialized (model={self.model_name}, "
            f"max_queries={self.max_queries}, search_depth={self.search_depth}, "
            f"thinking={self.thinking_level or 'default'})"
        )

    def _build_queries(self, claim: str, queries: List[str] | None = None) -> List[str]:
        """Pick up to ``max_queries`` German search queries for the claim.

        Preferred: the keyword queries the reformulator wrote (JevGate path), with the
        bare claim added as a safety net. Without them, heuristic variants of the claim.
        """
        picked: List[str] = []
        for q in [*(queries or []), claim]:
            q = (q or "").strip()
            if q and q.casefold() not in {p.casefold() for p in picked}:
                picked.append(q)
        if len(picked) < 2:
            picked = [
                claim,
                f"{claim} Statistik offizielle Zahlen Studie",
                f"{claim} aktuell",
            ]
        return picked[: max(1, self.max_queries)]

    async def _gather_evidence(self, claim: str, queries: List[str] | None = None) -> List[dict]:
        """Run the queries as parallel Tavily searches; flatten and de-duplicate results."""
        queries = self._build_queries(claim, queries)
        logger.info("Fast search queries: %s", queries)

        async def _one(q: str) -> dict:
            try:
                return await tavily_search(q, search_depth=self.search_depth)
            except Exception:
                logger.exception("Fast search failed for query: %s", q)
                return {"results": []}

        raw = await asyncio.gather(*[_one(q) for q in queries])
        seen_urls: set[str] = set()
        merged: List[dict] = []
        for res in raw:
            for item in res.get("results", []) or []:
                if _is_noise(item.get("url") or ""):
                    continue
                key = _url_key(item.get("url") or "")
                if key and key in seen_urls:
                    continue
                if key:
                    seen_urls.add(key)
                merged.append(item)
        # Primary sources first (stable within a tier, so Tavily's relevance order holds):
        # the model reads top-down and should reach for official data before the press.
        merged.sort(key=lambda r: source_tier(r.get("url", ""))[0])
        logger.info(
            "Fast search results: %s",
            [f"[{source_tier(r.get('url', ''))[1]}] {r.get('url', '')}" for r in merged],
        )
        return merged

    def _format_evidence(self, results: List[dict]) -> str:
        if not results:
            return "(keine Suchergebnisse)"
        lines = []
        for r in results:
            title = r.get("title", "")
            url = r.get("url", "")
            content = (r.get("content", "") or "")[: self.snippet_chars]
            lines.append(f"- [{source_tier(url)[1]}] {title} ({url}): {content}")
        return "\n".join(lines)

    async def check_claim_async(
        self,
        speaker: str,
        claim: str,
        context: str | None = None,
        episode_date: str | None = None,
        queries: List[str] | None = None,
    ) -> Dict[str, Any]:
        """Fast-check a single claim. Never raises; returns 'unklar' on failure.

        ``queries``: optional search queries (from the reformulator); falls back to
        heuristic variants of the claim.
        """
        logger.info(f"Fast-checking claim from {speaker}: {claim[:100]}...")
        try:
            results = await self._gather_evidence(claim, queries)
            user_message = (
                f"Kontext der Sendung: {context or '—'}\n"
                f"Sendedatum: {episode_date or '—'}\n"
                f"Sprecher: {speaker or '—'}\n"
                f"Behauptung: {claim}\n\n"
                f"Suchergebnisse aus vertrauenswürdigen Quellen:\n{self._format_evidence(results)}"
            )
            result = await self.agent.run(user_message)
            parsed = result.output.model_dump()
            # Only links the model actually saw: drops invented or mangled URLs.
            found = {r.get("url") for r in results}
            parsed["sources"] = [src for src in parsed.get("sources", []) if src.get("url") in found]
            if not parsed.get("speaker"):
                parsed["speaker"] = speaker
            if not parsed.get("original_claim"):
                parsed["original_claim"] = claim
            # Fast lane does no self-critique; keep the DB fields consistent.
            parsed["double_check"] = False
            parsed["critique_note"] = ""
            logger.info(f"Fast check done: consistency = {parsed.get('consistency', 'unknown')}")
            return parsed
        except Exception as e:
            logger.exception("Fast fact-check failed for claim")
            return {
                "speaker": speaker,
                "original_claim": claim,
                "consistency": "unklar",
                "evidence": f"Fehler bei der Schnellprüfung: {str(e)}",
                "sources": [],
                "double_check": False,
                "critique_note": "",
            }
