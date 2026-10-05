"""
Agent searches, a separate call judges: the agent (Flash via Requesty) only collects hits —
no verdict; then the live fast-check judge (FastFactChecker.agent, schema with the level
definitions) rules once on everything it found. A search without new hits tells the agent
to change strategy instead of rephrasing.

Per claim: Flash (via Requesty, thinking low) with a tavily_search tool (basic, trusted
domains) and the live FastVerdict schema; at most MAX_SEARCHES searches and MAX_REQUESTS
model calls per claim, and a hard Tavily budget for the whole run (BUDGET credits).
Records every query in order, so you can see whether it reacts to what it found.

    CLAIMS=claims.json OUT=react.jsonl python benchmarks/react_bench.py
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

from backend.services.fast_fact_checker import FastFactChecker, _is_noise, _url_key  # noqa: E402
from backend.services.search import tavily_search  # noqa: E402
from backend.services.trusted_domains import source_tier  # noqa: E402

CLAIMS = os.getenv("CLAIMS", "claims.json")
OUT = os.getenv("OUT", "react.jsonl")
MODEL = os.getenv("MODEL", "vertex/gemini-3.8-flash@eu")
THINKING = os.getenv("THINKING", "low")
MAX_SEARCHES = int(os.getenv("MAX_SEARCHES", "5"))
MAX_REQUESTS = int(os.getenv("MAX_REQUESTS", "8"))
BUDGET = int(os.getenv("BUDGET", "60"))  # Tavily credits for the whole run (basic = 1)

RESEARCH_PROMPT = f"""<Rolle>
Rechercheur für eine Faktenprüfung. Du sammelst Belege, du urteilst NICHT — das Urteil fällt
danach jemand anderes auf Basis aller Treffer, die du gefunden hast.
</Rolle>

<recherche>
Werkzeug: ``search`` (höchstens {MAX_SEARCHES} Suchen), vertrauenswürdige deutsche Quellen.
- Bestimme den Kern der Behauptung: die zentrale Tatsache oder Zahl, eine ausdrücklich
  behauptete Ursache gehört dazu.
- Beginne mit 2 Suchen aus verschiedenen Blickwinkeln (Kern, zuständige Datenquelle).
  Stichworte, 3–8 Wörter, auf Deutsch.
- Prüfe nach jeder Suche: Was fehlt noch, um den Kern zu beantworten? Suche gezielt danach —
  die Vergleichszahl, den Rang, den Stand zum genannten Zeitpunkt, die Originalquelle hinter
  einem Presse- oder Parteitreffer, Studien zu einer behaupteten Ursache. Suche auch nach
  Belegen, die der Behauptung widersprechen.
- Bringt eine Suche nichts Neues, formuliere sie nicht um: wechsle die Strategie (andere
  Größe, andere Quelle, Teilaspekt einzeln).
- Höre auf, sobald die Belege für ein Urteil reichen oder weitere Suchen nichts versprechen.
</recherche>

<ausgabe>
Gib in ``notiz`` in einem Satz an, was du gefunden hast und was fehlt.
</ausgabe>
"""


class Research(BaseModel):
    notiz: str = Field(description="Ein Satz: was gefunden wurde, was fehlt.")

state = {"credits": 0}


async def main() -> None:
    claims = json.loads(Path(CLAIMS).read_text())
    checker = FastFactChecker()
    provider = OpenAIProvider(base_url=os.getenv("REQUESTY_BASE_URL", "https://router.requesty.ai/v1"),
                              api_key=os.environ["REQUESTY_API_KEY"])
    model = OpenAIChatModel(MODEL, provider=provider,
                            settings=OpenAIChatModelSettings(openai_reasoning_effort=THINKING))

    with open(OUT, "w") as f:
        for c in claims:
            trace: list[dict] = []
            found: dict[str, dict] = {}

            async def search(query: str) -> str:
                """Suche in vertrauenswürdigen deutschen Quellen (Behörden, Statistik, Forschung).

                Args:
                    query: Deutsche Stichwort-Suchanfrage, 3–8 Wörter.
                """
                if len(trace) >= MAX_SEARCHES:
                    return "Suchlimit erreicht. Entscheide jetzt mit den vorliegenden Treffern."
                if state["credits"] >= BUDGET:
                    return "Suchbudget erschöpft. Entscheide jetzt mit den vorliegenden Treffern."
                state["credits"] += 1
                t0 = time.perf_counter()
                try:
                    res = await tavily_search(query, search_depth="basic")
                except Exception as e:
                    trace.append({"query": query, "error": repr(e)})
                    return "Suche fehlgeschlagen."
                hits, new = [], 0
                for r in res.get("results", []) or []:
                    url = r.get("url") or ""
                    if _is_noise(url):
                        continue
                    key = _url_key(url)
                    if key not in found:
                        new += 1
                    found[key] = r
                    hits.append(r)
                hits.sort(key=lambda r: source_tier(r.get("url", ""))[0])
                trace.append({"query": query, "hits": len(hits), "new": new,
                              "s": round(time.perf_counter() - t0, 2)})
                if hits and not new:
                    return ("Keine neuen Treffer — diese Richtung ist ausgeschöpft. Wechsle die "
                            "Strategie oder höre auf.\n" + checker._format_evidence(hits))
                return checker._format_evidence(hits)

            agent = Agent(model, output_type=Research, instructions=RESEARCH_PROMPT,
                          tools=[search], retries=1)
            msg = (f"Kontext der Sendung: {c.get('context') or '—'}\n"
                   f"Sendedatum: {c.get('episode_date') or '—'}\n"
                   f"Sprecher: {c.get('speaker') or '—'}\n"
                   f"Behauptung: {c['claim']}")
            t0 = time.perf_counter()
            res, note = {}, ""
            try:
                note = (await agent.run(msg, usage_limits=UsageLimits(request_limit=MAX_REQUESTS))).output.notiz
            except Exception as e:
                res["agent_error"] = repr(e)
            search_s = round(time.perf_counter() - t0, 2)
            hits = sorted(found.values(), key=lambda r: source_tier(r.get("url", ""))[0])
            t1 = time.perf_counter()
            try:
                out = (await checker.agent.run(
                    msg + "\n\nSuchergebnisse aus vertrauenswürdigen Quellen:\n" + checker._format_evidence(hits))).output
                urls = {r.get("url") for r in hits}
                res.update(consistency=out.consistency, evidence=out.evidence,
                           sources=[s.url for s in out.sources if s.url in urls])
            except Exception as e:
                res["error"] = repr(e)
            res.update(note=note, search_phase_s=search_s, judge_s=round(time.perf_counter() - t1, 2))
            res["hits"] = [{"url": r.get("url"), "title": r.get("title"),
                            "content": (r.get("content") or "")[:1200]} for r in hits]
            row = {"id": c.get("id"), "claim": c["claim"], "deep": c.get("deep_consistency", ""),
                   "before": c.get("prev_live", "unklar"), "react": res, "n_hits": len(found), "searches": trace,
                   "total_s": round(time.perf_counter() - t0, 2), "credits_so_far": state["credits"]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"#{row['id']:>3} vorher={row['before']:<8} ReAct={res.get('consistency', 'ERR'):<15} "
                  f"{len(trace)} Suchen {row['total_s']:5.1f}s  (Credits {state['credits']})", flush=True)
            for t in trace:
                print(f"      → {t['query']}  [{t.get('hits', '-')} Treffer, {t.get('new', '-')} neu]", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
