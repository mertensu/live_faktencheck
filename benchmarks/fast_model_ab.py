"""
A/B for the fast checker: synthesis model and/or Tavily results per query.

Per claim: reformulate once (GEMINI_MODEL_REFORMULATE) → search → synthesis with A and B.
With equal MAX_RESULTS_A/B the search runs once and both models see identical evidence, so
only the model differs; otherwise each variant searches the same queries with its own
max_results. No fallback chain: a failing model shows up as an error instead of silently
becoming another model.

    CLAIMS=claims.json uv run python benchmarks/fast_model_ab.py

Env: MODEL_A (default: current GEMINI_MODEL_FAST_CHECK default), THINKING_A (default low),
     MODEL_B (default gemini-2.5-pro; empty = run A only; names with "@" run via Requesty), THINKING_B (default: model default),
     MAX_RESULTS_A / MAX_RESULTS_B (default TAVILY_MAX_RESULTS or 5), REPEAT (default 1), OUT.
Claims may carry deep_consistency (reference from the deep checker); it is copied through.
"""

import os
import sys
import json
import time
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from pydantic_ai import Agent  # noqa: E402
from pydantic_ai.models.google import GoogleModel  # noqa: E402
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings  # noqa: E402
from pydantic_ai.providers.openai import OpenAIProvider  # noqa: E402

from backend.services.claim_extraction import ClaimExtractor  # noqa: E402
from backend.services.fast_fact_checker import FastFactChecker, FastVerdict, DEFAULT_MODEL  # noqa: E402
from backend.services.llm_base import _provider, settings_with_thinking  # noqa: E402

CLAIMS = os.getenv("CLAIMS", "claims.json")
OUT = os.getenv("OUT", "fast_model_ab.jsonl")
MODEL_A = os.getenv("MODEL_A", DEFAULT_MODEL)
THINKING_A = os.getenv("THINKING_A", "low")
MODEL_B = os.getenv("MODEL_B", "gemini-2.5-pro").strip()
THINKING_B = os.getenv("THINKING_B", "")
_MAX_DEFAULT = os.getenv("TAVILY_MAX_RESULTS", "5")
MAX_RESULTS_A = os.getenv("MAX_RESULTS_A", _MAX_DEFAULT)
MAX_RESULTS_B = os.getenv("MAX_RESULTS_B", _MAX_DEFAULT)
REPEAT = int(os.getenv("REPEAT", "1"))


def _agent(checker: FastFactChecker, model: str, thinking: str) -> Agent:
    """Gemini names go to Google directly; names with "@" (e.g. gpt-6-luna@eu) via Requesty,
    where the thinking level becomes the OpenAI reasoning effort."""
    if "@" in model:
        provider = OpenAIProvider(
            base_url=os.getenv("REQUESTY_BASE_URL", "https://router.requesty.ai/v1"),
            api_key=os.environ["REQUESTY_API_KEY"],
        )
        settings = OpenAIChatModelSettings(openai_reasoning_effort=thinking) if thinking else None
        llm = OpenAIChatModel(model, provider=provider)
    else:
        llm, settings = GoogleModel(model, provider=_provider()), settings_with_thinking(thinking)
    return Agent(
        llm, output_type=FastVerdict, instructions=checker.prompt_template,
        model_settings=settings, retries=1,
    )


async def _synth(agent: Agent, msg: str, found: set[str]) -> dict:
    t0 = time.perf_counter()
    try:
        out = (await agent.run(msg)).output
    except Exception as e:
        return {"error": repr(e), "synth_s": round(time.perf_counter() - t0, 2)}
    return {
        "synth_s": round(time.perf_counter() - t0, 2),
        "consistency": out.consistency,
        "evidence": out.evidence,
        "sources": [s.url for s in out.sources if s.url in found],
    }


async def _search(checker: FastFactChecker, claim: str, queries: list[str], max_results: str):
    # tavily_search reads TAVILY_MAX_RESULTS per call; A and B search one after the other.
    os.environ["TAVILY_MAX_RESULTS"] = max_results
    t0 = time.perf_counter()
    results = await checker._gather_evidence(claim, queries)
    return results, round(time.perf_counter() - t0, 2)


def _message(checker: FastFactChecker, c: dict, results: list[dict]) -> str:
    return (
        f"Kontext der Sendung: {c.get('context') or '—'}\n"
        f"Sendedatum: {c.get('episode_date') or '—'}\n"
        f"Sprecher: {c.get('speaker') or '—'}\n"
        f"Behauptung: {c['claim']}\n\n"
        f"Suchergebnisse aus vertrauenswürdigen Quellen:\n{checker._format_evidence(results)}"
    )


async def main() -> None:
    claims = json.loads(Path(CLAIMS).read_text())
    checker = FastFactChecker()
    a = _agent(checker, MODEL_A, THINKING_A)
    b = _agent(checker, MODEL_B, THINKING_B) if MODEL_B else None
    extractor = ClaimExtractor()

    rows = []
    with open(OUT, "w") as f:
        for run in range(REPEAT):
            for c in claims:
                guests = c.get("guests") or []
                if isinstance(guests, str):
                    guests = json.loads(guests or "[]")
                t0 = time.perf_counter()
                r = await extractor.reformulate_claim_async(
                    c["claim"], speaker=c.get("speaker", ""), guests=guests, context=c.get("context", ""),
                )
                queries = list(getattr(r, "search_queries", []) or [])
                reform_s = round(time.perf_counter() - t0, 2)
                res_a, search_a = await _search(checker, c["claim"], queries, MAX_RESULTS_A)
                if MAX_RESULTS_B == MAX_RESULTS_A or not b:
                    res_b, search_b = res_a, search_a
                else:
                    res_b, search_b = await _search(checker, c["claim"], queries, MAX_RESULTS_B)
                ra = await _synth(a, _message(checker, c, res_a), {x.get("url") for x in res_a})
                rb = (await _synth(b, _message(checker, c, res_b), {x.get("url") for x in res_b})
                      if b else {"skipped": True, "synth_s": 0.0})
                ra.update(search_s=search_a, n_results=len(res_a))
                rb.update(search_s=search_b, n_results=len(res_b))
                row = {
                    "run": run, "id": c.get("id"), "claim": c["claim"], "deep": c.get("deep_consistency", ""),
                    "queries": queries, "reform_s": reform_s, "A": ra, "B": rb,
                }
                rows.append(row)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                print(f"r{run} #{row['id']:>3} deep={row['deep'] or '—':<15} "
                      f"A={ra.get('consistency', 'ERR'):<15} {ra['n_results']:>2} hits {ra['synth_s']:5.1f}s | "
                      f"B={rb.get('consistency', 'ERR'):<15} {rb['n_results']:>2} hits {rb['synth_s']:5.1f}s")

    def avg(xs):
        return sum(xs) / len(xs) if xs else float("nan")

    print(f"\nA={MODEL_A} (thinking {THINKING_A or 'default'}, max_results {MAX_RESULTS_A})  "
          f"B={MODEL_B} (thinking {THINKING_B or 'default'}, max_results {MAX_RESULTS_B})")
    print(f"reform {avg([r['reform_s'] for r in rows]):.2f}s")
    for v in ("A", "B") if b else ("A",):
        ok = [r[v] for r in rows if "error" not in r[v]]
        ts = sorted(x["synth_s"] for x in ok)
        print(f"{v}: synth avg {avg(ts):.2f}s  median {ts[len(ts) // 2] if ts else float('nan'):.2f}s  "
              f"max {max(ts) if ts else float('nan'):.2f}s  errors {len(rows) - len(ok)}  "
              f"search {avg([x['search_s'] for x in ok]):.2f}s  hits {avg([x['n_results'] for x in ok]):.1f}")
        ref = [r for r in rows if r["deep"] and "error" not in r[v]]
        if ref:
            agree = sum(r[v]["consistency"] == r["deep"] for r in ref)
            print(f"   agrees with deep checker: {agree}/{len(ref)}")


if __name__ == "__main__":
    asyncio.run(main())
