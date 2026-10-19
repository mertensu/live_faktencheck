"""
Agent Fact Checker — a short research loop for the live lane (``LIVE_CHECKER=agent``).

The old deep checker (v0.2.0: ReAct agent, ~15–30 sequential searches, self-critique)
cut down to one research round: the model writes 4–5 searches at once, sees the hits, and
rules. Measured on 21 disputed claims (14.10.2026, 2 runs each): 36/42 verdicts within
the reference vs. 25/42 for the fast check, at about the same latency (p90 ~17–20 s per
check) and ~2.5 search credits per claim.

Search tools: ``suche`` on the trusted domains, ``presse_hinweis`` on PRESS_DOMAINS — press
hits come back without outlet, title or URL and are never cited (as in the fast check).
Rows are stored with check_depth="agent".
"""

import os
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, PromptedOutput, RunContext, UsageLimits

from backend.lang import (
    AGENT_CONSISTENCY_DESCRIPTION,
    AGENT_EVIDENCE_DESCRIPTION,
    AGENT_KURZ_DESCRIPTION,
    AGENT_OPEN_DESCRIPTION,
    AGENT_SOURCES_DESCRIPTION,
)
from backend.utils import load_prompt, log_text
from .fast_fact_checker import _MEDIA_RE, _is_noise, Source
from .llm_base import build_model, settings_with_thinking
from .search import tavily_search
from .trusted_domains import PRESS_DOMAINS, is_press, source_tier

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5-5@eu"

# Research vocabulary that must not reach viewers (the prompt bans it; this catches slips).
_RESEARCH_RE = re.compile(r"Suchtreffer|\bTreffer\b|Auszug|Auszüge|Suchergebnis")

_MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
           "September", "Oktober", "November", "Dezember"]


class AgentVerdict(BaseModel):
    consistency: Literal["hoch", "niedrig", "unklar", "keine Datenlage"] = Field(
        description=AGENT_CONSISTENCY_DESCRIPTION)
    evidence: str = Field(description=AGENT_EVIDENCE_DESCRIPTION)
    offen: str = Field(default="", description=AGENT_OPEN_DESCRIPTION)
    # After the long text: the model condenses what it has written, not the other way round.
    kurz: str = Field(default="", description=AGENT_KURZ_DESCRIPTION)
    sources: List[Source] = Field(description=AGENT_SOURCES_DESCRIPTION)


def _page_key(url: str) -> str:
    """The same page without scheme, www and trailing slash."""
    u = urlparse(url)
    return u.netloc.lower().removeprefix("www.") + u.path.rstrip("/") + ("?" + u.query if u.query else "")


@dataclass
class _Run:
    """Per-claim state the prompt, the tools and the output check share."""
    date: str
    rounds: set[int] = field(default_factory=set)
    searches: int = 0
    seen_urls: set[str] = field(default_factory=set)
    queries: List[str] = field(default_factory=list)
    # Per search: what came back and what was shown — (tier, score, url) per hit, dropped counts.
    hit_log: List[dict] = field(default_factory=list)
    asked_more: bool = False
    asked_media: bool = False
    asked_sources: bool = False


def _month_year(date: str | None) -> str:
    """'19. September 2025' -> 'September 2025'; empty -> the current month."""
    parts = (date or "").split()
    if parts and parts[0].endswith("."):
        return " ".join(parts[1:])
    return date or f"{_MONTHS[datetime.now().month - 1]} {datetime.now().year}"


# Headings the UI renders as such (formatBegruendung: a paragraph that is only **…**).
EVIDENCE_HEADING = "**Was die Quellen sagen**"
OPEN_HEADING = "**Was offen bleibt**"


def _long_text(out: AgentVerdict) -> str:
    """The long reasoning as stored in ``begruendung``: both parts under their headings."""
    parts = [EVIDENCE_HEADING, out.evidence.strip()]
    if out.offen.strip():
        parts += [OPEN_HEADING, out.offen.strip()]
    return "\n\n".join(parts)


class AgentFactChecker:
    """One research round of parallel searches, then a verdict."""

    check_depth = "agent"

    def __init__(self):
        self.model_name = os.getenv("GEMINI_MODEL_AGENT_CHECK", DEFAULT_MODEL)
        thinking = os.getenv("GEMINI_THINKING_AGENT_CHECK", "low")
        # Rounds of searches: one measured as good as two (18/22 both) at two thirds the time.
        self.max_rounds = int(os.getenv("AGENT_CHECK_ROUNDS", "1"))
        # A run that searched once (seen: one query, a party source, a wrong "niedrig") is
        # sent back for more before it may rule. Not 3: the extra round costs ~12 s, and 13
        # of 42 measured checks searched twice.
        self.min_searches = int(os.getenv("AGENT_CHECK_MIN_SEARCHES", "2"))
        self.max_results = int(os.getenv("TAVILY_MAX_RESULTS", "5"))
        # Retrieval window: fetch more hits than the model sees, so that an official or
        # research page Tavily ranks 6th–10th among the ~109 trusted domains still makes it
        # into the five shown (the tier sort below decides). Same credits per search.
        self.fetch_results = max(int(os.getenv("AGENT_FETCH_RESULTS", "10")), self.max_results)
        # Relevance floor on Tavily's score: a hit below it is dropped before the tier sort,
        # so an off-topic official page cannot displace a relevant research page.
        # 0.1 removes only the plainly off-topic (measured: every hit below it). 0.2 was
        # measured too: it emptied 6 of 171 searches and doubled the searches with fewer
        # than three hits, with no gain in verdicts.
        self.min_score = float(os.getenv("AGENT_MIN_SCORE", "0.1"))
        # Host cap: in 35 of 159 measured searches all five shown hits came from one host
        # (one ministry's press archive), while research pages from the pool were cut. At
        # most this many hits per host are shown while others are left; the rest fill up.
        self.max_per_host = int(os.getenv("AGENT_MAX_PER_HOST", "2"))
        self.prompt_template = load_prompt("agent_fact_checker.md")

        self.agent = Agent(
            # The calls carry 10–40k tokens of hits; the live lane's 12 s Requesty timeout
            # would cut the verdict call off.
            build_model(self.model_name, thinking=thinking,
                        timeout=float(os.getenv("AGENT_CHECK_TIMEOUT_S", "45"))),
            # Prompted output: Claude with thinking rejects the forced tool choice that tool
            # output needs.
            output_type=PromptedOutput(AgentVerdict),
            deps_type=_Run,
            model_settings=settings_with_thinking(thinking),
            retries=2,
        )
        self.agent.instructions(self._instructions)
        self.agent.tool(self.suche)
        self.agent.tool(self.presse_hinweis)
        self.agent.output_validator(self._check_output)
        logger.info(f"AgentFactChecker initialized (model={self.model_name}, thinking={thinking}, "
                    f"rounds={self.max_rounds}, min_searches={self.min_searches}, "
                    f"fetch={self.fetch_results}/show={self.max_results}, min_score={self.min_score}, "
                    f"max_per_host={self.max_per_host})")

    def _instructions(self, ctx: RunContext[_Run]) -> str:
        return self.prompt_template.replace("{current_date}", ctx.deps.date)

    def _may_search(self, ctx: RunContext[_Run]) -> bool:
        # run_step counts model responses; the tool calls of one response share it.
        run = ctx.deps
        if ctx.run_step in run.rounds or len(run.rounds) < self.max_rounds or run.searches < self.min_searches:
            run.rounds.add(ctx.run_step)
            run.searches += 1
            return True
        return False

    async def _search(self, ctx: RunContext[_Run], query: str, domains: list[str] | None) -> list[dict]:
        ctx.deps.queries.append(query if domains is None else f"[presse] {query}")
        try:
            res = await tavily_search(query, include_domains=domains, max_results=self.fetch_results)
        except Exception:
            logger.exception("Agent check: search failed for query: %s", query)
            return []
        raw = [r for r in res.get("results", []) or [] if r.get("url")]
        # Tavily returns the same page under http/https and with/without www (seen: one
        # study five times); the duplicates would take slots and count against the host cap.
        seen_keys: set[str] = set()
        hits = []
        for r in raw:
            key = _page_key(r["url"])
            if _is_noise(r["url"]) or key in seen_keys:
                continue
            seen_keys.add(key)
            hits.append(r)
        # A hit without a score (older API shapes, tests) is kept.
        relevant = [r for r in hits if r.get("score") is None or float(r["score"]) >= self.min_score]
        relevant.sort(key=lambda r: source_tier(r["url"])[0])  # stable: official data first
        shown = self._cap_hosts(relevant)
        # Every fetched hit with its fate, to calibrate the window and the floor from runs.
        ctx.deps.hit_log.append({
            "query": query, "fetched": len(raw), "noise": len(raw) - len(hits),
            "low_score": len(hits) - len(relevant),
            "hits": [(source_tier(r["url"])[1], round(float(r.get("score") or 0.0), 3), r["url"],
                      "shown" if r in shown else "dup" if r not in hits and not _is_noise(r["url"])
                      else "noise" if r not in hits else "low" if r not in relevant else "cut")
                     for r in raw],
        })
        return shown

    def _cap_hosts(self, hits: list[dict]) -> list[dict]:
        """The first max_results hits with at most max_per_host per host; if that leaves
        room, the skipped hits fill it in order."""
        per_host: Dict[str, int] = {}
        shown, skipped = [], []
        for r in hits:
            host = urlparse(r["url"]).netloc.lower().removeprefix("www.")
            if per_host.get(host, 0) < self.max_per_host:
                per_host[host] = per_host.get(host, 0) + 1
                shown.append(r)
            else:
                skipped.append(r)
        return (shown + skipped)[: self.max_results]

    async def suche(self, ctx: RunContext[_Run], query: str) -> str:
        """Durchsucht vertrauenswürdige deutsche Quellen (Behörden, Statistikämter, Forschung,
        EU, Faktenchecks) und liefert Treffer mit URL, Titel, Quellentyp und Auszug.

        Args:
            query: Suchanfrage auf Deutsch.
        """
        if not self._may_search(ctx):
            return "Recherche beendet. Fälle jetzt dein Urteil mit den vorliegenden Belegen."
        hits = [h for h in await self._search(ctx, query, None) if not is_press(h["url"])]
        ctx.deps.seen_urls.update(h["url"] for h in hits)
        return "\n\n".join(f"[{source_tier(h['url'])[1]}] {h.get('title', '')}\nURL: {h['url']}\n{h.get('content', '')}"
                           for h in hits) or "Keine Treffer."

    async def presse_hinweis(self, ctx: RunContext[_Run], query: str) -> str:
        """Durchsucht Presseartikel. Die Treffer sind nur Hinweise darauf, woher eine Zahl
        stammt (Studie, Institut, Ministerium) oder wer sie bestreitet — keine Belege. Sie
        kommen ohne Titel und URL, dürfen nicht als Quelle genannt werden; suche danach mit
        `suche` die Originalquelle.

        Args:
            query: Suchanfrage auf Deutsch.
        """
        if not self._may_search(ctx):
            return "Recherche beendet. Fälle jetzt dein Urteil mit den vorliegenden Belegen."
        hits = await self._search(ctx, query, PRESS_DOMAINS)
        return "\n\n".join(f"[Hinweis] {h.get('content', '')}" for h in hits) or "Keine Treffer."

    def _check_output(self, ctx: RunContext[_Run], output: AgentVerdict) -> AgentVerdict:
        """At most one request each: search more, list the sources, or rewrite a text that names the press."""
        run = ctx.deps
        if run.searches < self.min_searches and not run.asked_more:
            run.asked_more = True
            raise ModelRetry(
                f"Du hast erst {run.searches} Suche(n) gestellt. Stelle weitere Suchanfragen gleichzeitig "
                "(amtliche Statistik, konkreter Wert für Zeitraum und Region, Gegenbelege), dann urteile.")
        if not output.sources and output.consistency != "keine Datenlage" and run.seen_urls and not run.asked_sources:
            run.asked_sources = True
            raise ModelRetry("Die Quellenliste ist leer. Führe in `sources` die 1–4 Quellen aus den Suchergebnissen "
                             "auf, auf die sich deine Begründung stützt (URL und Titel).")
        text = f"{output.evidence} {output.offen} {output.kurz}"
        found = sorted(set(_MEDIA_RE.findall(text)) | set(_RESEARCH_RE.findall(text)))
        if found and not run.asked_media:
            run.asked_media = True
            raise ModelRetry(
                f"Die Begründung nennt {', '.join(found)}. Formuliere sie neu, ohne Zeitungen, Sender, "
                "„Presse“ oder „Hinweis“ zu nennen und ohne Wörter wie „Treffer“ oder „Auszug“; nenne nur den "
                "Urheber einer Angabe (Institut, Person, Behörde) und sprich von „den geprüften Quellen“.")
        return output

    async def check_claim_async(
        self,
        speaker: str,
        claim: str,
        context: str | None = None,
        episode_date: str | None = None,
        queries: List[str] | None = None,
    ) -> Dict[str, Any]:
        """Check a single claim. Never raises; returns 'unklar' on failure.

        ``queries`` (the reformulator's) are not used: the agent writes its own searches.
        """
        logger.info(f"Agent-checking claim from {speaker}: {log_text(claim, 100)}")
        run = _Run(date=_month_year(episode_date))
        try:
            message = json.dumps({"context": context or "", "sprecher": speaker or "",
                                  "sendedatum": run.date, "behauptung": claim},
                                 ensure_ascii=False, indent=2)
            result = await self.agent.run(message, deps=run,
                                          usage_limits=UsageLimits(request_limit=int(os.getenv("AGENT_CHECK_REQUEST_LIMIT", "6"))))
            out = result.output
            # Only links the model actually saw (drops invented or mangled URLs), never press.
            sources = [s.model_dump() for s in out.sources if s.url in run.seen_urls and not is_press(s.url)]
            logger.info(f"Agent check done: consistency = {out.consistency}, searches = {run.queries}")
            return {
                "speaker": speaker, "original_claim": claim, "consistency": out.consistency,
                "evidence": _long_text(out), "kurz": out.kurz, "sources": sources,
                "double_check": False, "critique_note": "",
                # Stored with the row: the agent writes its own searches ("[presse] …" for press).
                "search_queries": run.queries,
            }
        except Exception as e:
            logger.exception("Agent fact-check failed for claim")
            return {
                "speaker": speaker, "original_claim": claim, "consistency": "unklar",
                "evidence": f"Fehler bei der Prüfung: {str(e)}", "sources": [],
                "double_check": False, "critique_note": "",
            }
