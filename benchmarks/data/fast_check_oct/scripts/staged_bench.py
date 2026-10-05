"""
Fast check, then a targeted follow-up for undecided verdicts — as it would run live.

Per claim:
  0. Live fast check: reformulator queries → parallel Tavily (basic) → judge (FastFactChecker).
  1. Only if the verdict is 'unklar'/'keine Datenlage': an agent sees the claim, the queries
     already run, the hits found and why the judge was undecided, and searches in ROUNDS —
     one tool call takes up to 3 queries, run in parallel; at most MAX_ROUNDS rounds and
     MAX_SEARCHES searches. It does not judge.
  2. The same judge rules once more on all hits (phase 0 + phase 1).

    CLAIMS=claims.json OUT=staged.jsonl python benchmarks/staged_bench.py
"""

import os
import sys
import json
import time
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import BaseModel, Field  # noqa: E402
from pydantic_ai import Agent, UsageLimits  # noqa: E402
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings  # noqa: E402
from pydantic_ai.providers.openai import OpenAIProvider  # noqa: E402

import backend.services.fast_fact_checker as ffc  # noqa: E402
from backend.services.claim_extraction import ClaimExtractor  # noqa: E402
from backend.services.fast_fact_checker import FastFactChecker, _is_noise, _url_key  # noqa: E402
from backend.services.search import tavily_search  # noqa: E402
from backend.services.trusted_domains import source_tier  # noqa: E402

CLAIMS = os.getenv("CLAIMS", "claims.json")
OUT = os.getenv("OUT", "staged.jsonl")
MODEL = os.getenv("MODEL", "vertex/gemini-3.8-flash@eu")
THINKING = os.getenv("THINKING", "low")
MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "2"))
MAX_SEARCHES = int(os.getenv("MAX_SEARCHES", "5"))
PER_ROUND = 3
BUDGET = int(os.getenv("BUDGET", "80"))
UNDECIDED = ("unklar", "keine Datenlage")

RESEARCH_PROMPT = f"""<Rolle>
Rechercheur für eine Faktenprüfung. Eine erste Prüfung kam zu keinem klaren Urteil. Du
suchst gezielt nach dem, was fehlt; du urteilst NICHT — das Urteil fällt danach auf Basis
aller Treffer.
</Rolle>

<recherche>
Werkzeug: ``search`` nimmt 1–{PER_ROUND} Anfragen auf einmal und führt sie gleichzeitig aus.
Höchstens {MAX_ROUNDS} Runden. Stichworte, 3–8 Wörter, auf Deutsch.
- Runde 1: Schließe die Lücke, die die erste Prüfung nennt — die Vergleichszahl, den Rang,
  den Stand zum genannten Zeitpunkt, die Originalquelle hinter einem Presse- oder
  Parteitreffer, Studien zu einer behaupteten Ursache. Nutze verschiedene Blickwinkel,
  wiederhole keine bisherige Anfrage.
- Runde 2 nur, wenn Runde 1 die Lücke nicht geschlossen hat und eine andere Strategie
  (andere Größe, andere Quelle, Teilaspekt einzeln) etwas verspricht.
</recherche>

<ausgabe>
Gib in ``notiz`` in einem Satz an, was du gefunden hast und was fehlt.
</ausgabe>
"""


class Research(BaseModel):
    notiz: str = Field(description="Ein Satz: was gefunden wurde, was fehlt.")


state = {"credits": 0}


def _message(c: dict) -> str:
    return (f"Kontext der Sendung: {c.get('context') or '—'}\n"
            f"Sendedatum: {c.get('episode_date') or '—'}\n"
            f"Sprecher: {c.get('speaker') or '—'}\n"
            f"Behauptung: {c['claim']}")


async def _tavily(q: str) -> list[dict]:
    if state["credits"] >= BUDGET:
        return []
    state["credits"] += 1
    try:
        return (await tavily_search(q, search_depth="basic")).get("results", []) or []
    except Exception:
        return []


async def _judge(checker: FastFactChecker, c: dict, hits: list[dict]) -> tuple[dict, float]:
    hits = sorted(hits, key=lambda r: source_tier(r.get("url", ""))[0])
    t0 = time.perf_counter()
    try:
        out = (await checker.agent.run(
            _message(c) + "\n\nSuchergebnisse aus vertrauenswürdigen Quellen:\n" + checker._format_evidence(hits))).output
        urls = {r.get("url") for r in hits}
        res = {"consistency": out.consistency, "evidence": out.evidence,
               "sources": [s.url for s in out.sources if s.url in urls]}
    except Exception as e:
        res = {"error": repr(e)}
    return res, round(time.perf_counter() - t0, 2)


async def main() -> None:
    claims = json.loads(Path(CLAIMS).read_text())
    checker = FastFactChecker()
    extractor = ClaimExtractor()
    provider = OpenAIProvider(base_url=os.getenv("REQUESTY_BASE_URL", "https://router.requesty.ai/v1"),
                              api_key=os.environ["REQUESTY_API_KEY"])
    model = OpenAIChatModel(MODEL, provider=provider,
                            settings=OpenAIChatModelSettings(openai_reasoning_effort=THINKING))

    # Phase 0 searches go through tavily_search inside the checker: count them too.
    orig = ffc.tavily_search

    async def counted(q, **kw):
        state["credits"] += 1
        return await orig(q, **kw)
    ffc.tavily_search = counted

    with open(OUT, "w") as f:
        for c in claims:
            row = {"id": c.get("id"), "claim": c["claim"], "deep": c.get("deep_consistency", "")}
            guests = c.get("guests") or []
            if isinstance(guests, str):
                guests = json.loads(guests or "[]")
            # Phase 0: the live fast check.
            t0 = time.perf_counter()
            r = await extractor.reformulate_claim_async(c["claim"], speaker=c.get("speaker", ""),
                                                        guests=guests, context=c.get("context", ""))
            queries = list(getattr(r, "search_queries", []) or [])
            reform_s = round(time.perf_counter() - t0, 2)
            t1 = time.perf_counter()
            hits0 = await checker._gather_evidence(c["claim"], queries)
            search0_s = round(time.perf_counter() - t1, 2)
            v1, judge1_s = await _judge(checker, c, hits0)
            row["fast"] = {**v1, "queries": queries, "n_hits": len(hits0), "reform_s": reform_s,
                           "search_s": search0_s, "judge_s": judge1_s}
            row["follow"] = None
            if v1.get("consistency") in UNDECIDED:
                found = {_url_key(h.get("url") or ""): h for h in hits0}
                rounds: list[dict] = []

                async def search(queries: list[str]) -> str:
                    """Führe 1–3 Suchanfragen gleichzeitig aus (vertrauenswürdige deutsche Quellen).

                    Args:
                        queries: 1–3 deutsche Stichwort-Suchanfragen, je 3–8 Wörter.
                    """
                    done = sum(len(x["queries"]) for x in rounds)
                    if len(rounds) >= MAX_ROUNDS or done >= MAX_SEARCHES:
                        return "Suchlimit erreicht."
                    qs = [q for q in queries if q.strip()][:min(PER_ROUND, MAX_SEARCHES - done)]
                    ts = time.perf_counter()
                    results = await asyncio.gather(*(_tavily(q) for q in qs))
                    new = []
                    for res in results:
                        for h in res:
                            url = h.get("url") or ""
                            key = _url_key(url)
                            if _is_noise(url) or key in found:
                                continue
                            found[key] = h
                            new.append(h)
                    rounds.append({"queries": qs, "new": len(new), "s": round(time.perf_counter() - ts, 2)})
                    if not new:
                        return "Keine neuen Treffer — diese Richtung ist ausgeschöpft."
                    new.sort(key=lambda r: source_tier(r.get("url", ""))[0])
                    return checker._format_evidence(new)

                agent = Agent(model, output_type=Research, instructions=RESEARCH_PROMPT,
                              tools=[search], retries=1)
                seen = "\n".join(f"- {h.get('title', '')} ({h.get('url', '')})" for h in hits0) or "(keine)"
                msg = (_message(c) + f"\n\nBisherige Suchanfragen: {'; '.join(queries)}\n"
                       f"Bisherige Treffer:\n{seen}\n\n"
                       f"Erste Prüfung: {v1.get('consistency')} — {v1.get('evidence', '')}")
                t2 = time.perf_counter()
                note = ""
                try:
                    note = (await agent.run(msg, usage_limits=UsageLimits(request_limit=MAX_ROUNDS + 2))).output.notiz
                except Exception as e:
                    note = f"ERR {e!r}"
                agent_s = round(time.perf_counter() - t2, 2)
                v2, judge2_s = await _judge(checker, c, list(found.values()))
                row["follow"] = {**v2, "note": note, "rounds": rounds, "n_hits": len(found),
                                 "agent_s": agent_s, "judge_s": judge2_s,
                                 "hits": [{"url": h.get("url"), "title": h.get("title")} for h in found.values()]}
            row["credits_so_far"] = state["credits"]
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            fu = row["follow"]
            print(f"#{row['id']:>3} schnell={v1.get('consistency', 'ERR')}"
                  + (f" -> nach={fu.get('consistency', 'ERR')} (+{fu['agent_s'] + fu['judge_s']:.1f}s, "
                     f"{len(fu['rounds'])} Runden)" if fu else "")
                  + f"  Credits {state['credits']}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
