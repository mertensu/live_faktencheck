"""
ReAct with a strict limit: does the model correct itself and fill gaps by searching again?

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

from pydantic_ai import Agent, UsageLimits  # noqa: E402
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings  # noqa: E402
from pydantic_ai.providers.openai import OpenAIProvider  # noqa: E402

from backend.services.fast_fact_checker import FastFactChecker, FastVerdict, _is_noise, _url_key  # noqa: E402
from backend.services.search import tavily_search  # noqa: E402
from backend.services.trusted_domains import source_tier  # noqa: E402

CLAIMS = os.getenv("CLAIMS", "claims.json")
OUT = os.getenv("OUT", "react.jsonl")
MODEL = os.getenv("MODEL", "vertex/gemini-3.8-flash@eu")
THINKING = os.getenv("THINKING", "low")
MAX_SEARCHES = int(os.getenv("MAX_SEARCHES", "5"))
MAX_REQUESTS = int(os.getenv("MAX_REQUESTS", "8"))
BUDGET = int(os.getenv("BUDGET", "100"))  # Tavily credits for the whole run (basic = 1)

REACT_RULES = f"""
<recherche>
Du recherchierst selbst mit dem Werkzeug ``tavily_search`` (höchstens {MAX_SEARCHES} Suchen).
- Beginne mit 2–3 Suchen aus verschiedenen Blickwinkeln (Kern, zuständige Datenquelle,
  Entwicklung). Stichworte, 3–8 Wörter, auf Deutsch.
- Lies die Treffer und prüfe: Beantworten sie den Kern? Wenn nicht, suche gezielt nach dem,
  was fehlt — die Vergleichszahl, den Rang, die Originalquelle hinter einem Presse- oder
  Parteitreffer, den nächstliegenden Stand (Quartal, Vorjahr), Studien zu einer behaupteten
  Ursache (auch widersprechende). Wiederhole keine Suche.
- Entscheide, sobald die Belege reichen. Bleibt eine Lücke nach gezielter Nachsuche, sag das.
</recherche>
"""

state = {"credits": 0}


async def main() -> None:
    claims = json.loads(Path(CLAIMS).read_text())
    checker = FastFactChecker()
    prompt = checker.prompt_template.replace("du recherchierst NICHT selbst weiter", "du recherchierst selbst")
    prompt = prompt.replace("nur auf Basis der mitgelieferten\nSuchergebnisse", "auf Basis deiner Suchergebnisse")
    prompt += REACT_RULES
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
                return checker._format_evidence(hits)

            agent = Agent(model, output_type=FastVerdict, instructions=prompt,
                          tools=[search], retries=1)
            msg = (f"Kontext der Sendung: {c.get('context') or '—'}\n"
                   f"Sendedatum: {c.get('episode_date') or '—'}\n"
                   f"Sprecher: {c.get('speaker') or '—'}\n"
                   f"Behauptung: {c['claim']}")
            t0 = time.perf_counter()
            try:
                out = (await agent.run(msg, usage_limits=UsageLimits(request_limit=MAX_REQUESTS))).output
                urls = {r.get("url") for r in found.values()}
                res = {"consistency": out.consistency, "evidence": out.evidence,
                       "sources": [s.url for s in out.sources if s.url in urls]}
            except Exception as e:
                res = {"error": repr(e)}
            row = {"id": c.get("id"), "claim": c["claim"], "deep": c.get("deep_consistency", ""),
                   "before": c.get("prev_live", "unklar"), "react": res, "searches": trace,
                   "total_s": round(time.perf_counter() - t0, 2), "credits_so_far": state["credits"]}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"#{row['id']:>3} vorher={row['before']:<8} ReAct={res.get('consistency', 'ERR'):<15} "
                  f"{len(trace)} Suchen {row['total_s']:5.1f}s  (Credits {state['credits']})", flush=True)
            for t in trace:
                print(f"      → {t['query']}  [{t.get('hits', '-')} Treffer, {t.get('new', '-')} neu]", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
