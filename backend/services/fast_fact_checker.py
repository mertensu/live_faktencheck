"""
Fast Fact Checker — first-pass verdict for the live streaming lane.

Unlike ``FactChecker`` (a ReAct agent that loops search→reason up to ~35 times and
then self-critiques), this service is built for latency: it fires a few low-latency
Tavily searches *in parallel*, then makes a single synthesis call that returns only a
``consistency`` level (Vertrauenslevel) and one short sentence. No agent loop, no
self-critique. A claim can later be upgraded to a full verdict by the deep
``FactChecker`` (see check_depth="fast" rows).
"""

import os
import asyncio
import logging
from typing import List, Dict, Any, Literal

from pydantic import BaseModel, Field

from backend.utils import load_prompt
from backend.lang import (
    SOURCE_URL_DESCRIPTION,
    SOURCE_TITLE_DESCRIPTION,
    CONSISTENCY_DESCRIPTION,
    SOURCES_DESCRIPTION,
)
from .llm_base import build_model, MODEL_SETTINGS
from .search import tavily_search
from pydantic_ai import Agent

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3.6-flash"


class Source(BaseModel):
    url: str = Field(description=SOURCE_URL_DESCRIPTION)
    title: str = Field(description=SOURCE_TITLE_DESCRIPTION)


class FastVerdict(BaseModel):
    """A fast first-pass verdict. Field names mirror ``FactCheckResponse`` so the
    same ``build_fact_check_dict`` mapping stores it unchanged."""
    speaker: str = ""
    original_claim: str = ""
    consistency: Literal["hoch", "niedrig", "unklar", "keine Datenlage"] = Field(
        description=CONSISTENCY_DESCRIPTION
    )
    evidence: str = Field(
        description="EINE kurze, prägnante deutschsprachige Einschätzung (ein Satz)."
    )
    sources: List[Source] = Field(default_factory=list, description=SOURCES_DESCRIPTION)


class FastFactChecker:
    """Fast, loop-free fact-check: parallel Tavily searches + one synthesis call."""

    def __init__(self):
        self.model_name = os.getenv("GEMINI_MODEL_FAST_CHECK", DEFAULT_MODEL)
        self.fallback_model_name = os.getenv("GEMINI_MODEL_FACT_CHECKER_FALLBACK", "gemini-3-flash-preview")
        self.max_queries = int(os.getenv("FAST_SEARCH_MAX_QUERIES", "3"))
        # This path favours latency; keep it on a fast Tavily tier independent of the
        # deep checker's TAVILY_SEARCH_DEPTH.
        self.search_depth = os.getenv("FAST_TAVILY_SEARCH_DEPTH", "fast")

        self.prompt_template = load_prompt("fast_fact_checker.md")

        # No tools: we run the searches ourselves and hand the results to the agent.
        self.agent = Agent(
            build_model(self.model_name, self.fallback_model_name),
            output_type=FastVerdict,
            instructions=self.prompt_template,
            model_settings=MODEL_SETTINGS,
            retries=1,
        )

        logger.info(
            f"FastFactChecker initialized (model={self.model_name}, "
            f"max_queries={self.max_queries}, search_depth={self.search_depth})"
        )

    def _build_queries(self, claim: str) -> List[str]:
        """Derive up to ``max_queries`` German search queries from the claim.

        Heuristic variants (no extra LLM call to keep latency low): the bare claim,
        one nudged toward official data, one toward recency. Trimmed to max_queries.
        """
        variants = [
            claim,
            f"{claim} Statistik offizielle Zahlen Studie",
            f"{claim} aktuell",
        ]
        return variants[: max(1, self.max_queries)]

    async def _gather_evidence(self, claim: str) -> List[dict]:
        """Run the query variants as parallel Tavily searches; flatten results."""
        queries = self._build_queries(claim)

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
                url = item.get("url")
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                merged.append(item)
        return merged

    def _format_evidence(self, results: List[dict]) -> str:
        if not results:
            return "(keine Suchergebnisse)"
        lines = []
        for r in results:
            title = r.get("title", "")
            url = r.get("url", "")
            content = (r.get("content", "") or "")[:500]
            lines.append(f"- {title} ({url}): {content}")
        return "\n".join(lines)

    async def check_claim_async(
        self,
        speaker: str,
        claim: str,
        context: str | None = None,
        episode_date: str | None = None,
    ) -> Dict[str, Any]:
        """Fast-check a single claim. Never raises; returns 'unklar' on failure."""
        logger.info(f"Fast-checking claim from {speaker}: {claim[:100]}...")
        try:
            results = await self._gather_evidence(claim)
            user_message = (
                f"Kontext der Sendung: {context or '—'}\n"
                f"Sendedatum: {episode_date or '—'}\n"
                f"Sprecher: {speaker or '—'}\n"
                f"Behauptung: {claim}\n\n"
                f"Suchergebnisse aus vertrauenswürdigen Quellen:\n{self._format_evidence(results)}"
            )
            result = await self.agent.run(user_message)
            parsed = result.output.model_dump()
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
