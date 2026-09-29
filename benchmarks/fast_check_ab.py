"""
A/B for the live fast checker: old setup vs. new setup on real claims.

  old: 3 heuristic query variants (claim + suffixes), Tavily "fast", 500-char snippets,
       old synthesis prompt (OLD_PROMPT_FILE, e.g. `git show <rev>:prompts/fast_fact_checker.md`)
  new: reformulator (GEMINI_MODEL_REFORMULATE) writes search queries, Tavily "basic",
       up to 5 queries, 1200-char snippets, current synthesis prompt

Timing per variant: reformulation (new only), search, synthesis. The live lane already
runs a reformulation call, so the latency that matters is the *difference* between
flash-lite and flash reformulation — measured separately on the same claims.

Input: a JSON list of claims (id, speaker, claim, context, guests, episode_date, and
optionally deep_consistency/deep_evidence as a reference), e.g. from `pull-db.sh`:

    CLAIMS=claims.json OLD_PROMPT_FILE=old_prompt.md uv run python benchmarks/fast_check_ab.py

Writes OUT (default fast_check_ab.jsonl) and prints a summary table.
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

from backend.services.claim_extraction import ClaimExtractor  # noqa: E402
from backend.services.fast_fact_checker import FastFactChecker, FastVerdict  # noqa: E402
from backend.services.llm_base import build_model, MODEL_SETTINGS  # noqa: E402

CLAIMS = os.getenv("CLAIMS", "claims.json")
OLD_PROMPT_FILE = os.getenv("OLD_PROMPT_FILE", "")
OUT = os.getenv("OUT", "fast_check_ab.jsonl")
LITE_MODEL = os.getenv("REFORMULATE_LITE_MODEL", "gemini-3.5-flash-lite")
NEW_DEPTH = os.getenv("NEW_DEPTH", "basic")
NEW_MAX_QUERIES = int(os.getenv("NEW_MAX_QUERIES", "5"))
# Skip the old setup + lite reformulation (already measured) to iterate on "new" only.
NEW_ONLY = os.getenv("NEW_ONLY", "") == "1"


def _checker(depth: str, max_queries: int, snippet_chars: int, prompt: str | None) -> FastFactChecker:
    os.environ["FAST_TAVILY_SEARCH_DEPTH"] = depth
    os.environ["FAST_SEARCH_MAX_QUERIES"] = str(max_queries)
    os.environ["FAST_SNIPPET_CHARS"] = str(snippet_chars)
    c = FastFactChecker()
    if prompt:
        c.agent = Agent(
            build_model(c.model_name, c.fallback_model_name),
            output_type=FastVerdict, instructions=prompt,
            model_settings=MODEL_SETTINGS, retries=1,
        )
    return c


async def _timed_check(checker: FastFactChecker, c: dict, queries: list[str] | None) -> dict:
    """Same steps as check_claim_async, timed separately (search vs. synthesis)."""
    t0 = time.perf_counter()
    results = await checker._gather_evidence(c["claim"], queries)
    t1 = time.perf_counter()
    msg = (
        f"Kontext der Sendung: {c.get('context') or '—'}\n"
        f"Sendedatum: {c.get('episode_date') or '—'}\n"
        f"Sprecher: {c.get('speaker') or '—'}\n"
        f"Behauptung: {c['claim']}\n\n"
        f"Suchergebnisse aus vertrauenswürdigen Quellen:\n{checker._format_evidence(results)}"
    )
    out = (await checker.agent.run(msg)).output
    t2 = time.perf_counter()
    return {
        "queries": checker._build_queries(c["claim"], queries),
        "n_results": len(results),
        "search_s": round(t1 - t0, 2),
        "synth_s": round(t2 - t1, 2),
        "consistency": out.consistency,
        "evidence": out.evidence,
        "sources": [s.url for s in out.sources],
    }


async def _reformulate(agent_owner: ClaimExtractor, c: dict) -> tuple[list[str], float]:
    guests = c.get("guests") or []
    if isinstance(guests, str):
        guests = json.loads(guests or "[]")
    t0 = time.perf_counter()
    r = await agent_owner.reformulate_claim_async(
        c["claim"], speaker=c.get("speaker", ""), guests=guests, context=c.get("context", ""),
    )
    return list(getattr(r, "search_queries", []) or []), round(time.perf_counter() - t0, 2)


async def main() -> None:
    claims = json.loads(Path(CLAIMS).read_text())
    old_prompt = Path(OLD_PROMPT_FILE).read_text() if OLD_PROMPT_FILE else None

    # The old setup ran with the model's default thinking; the new one reads
    # GEMINI_THINKING_FAST_CHECK / GEMINI_THINKING_REFORMULATE (default "low").
    thinking = os.environ.get("GEMINI_THINKING_FAST_CHECK")
    os.environ["GEMINI_THINKING_FAST_CHECK"] = ""
    old = _checker("fast", 3, 500, old_prompt)
    if thinking is None:
        del os.environ["GEMINI_THINKING_FAST_CHECK"]
    else:
        os.environ["GEMINI_THINKING_FAST_CHECK"] = thinking
    new = _checker(NEW_DEPTH, NEW_MAX_QUERIES, 1200, None)
    extractor = ClaimExtractor()  # GEMINI_MODEL_REFORMULATE (default flash)
    os.environ["GEMINI_MODEL_REFORMULATE"] = LITE_MODEL
    lite = ClaimExtractor()

    rows = []
    with open(OUT, "w") as f:
        for c in claims:
            row = {"id": c.get("id"), "claim": c["claim"], "deep": c.get("deep_consistency", "")}
            try:
                if not NEW_ONLY:
                    row["old"] = await _timed_check(old, c, None)
                    _, row["reform_lite_s"] = await _reformulate(lite, c)
                queries, row["reform_s"] = await _reformulate(extractor, c)
                row["new"] = await _timed_check(new, c, queries)
            except Exception as e:  # keep going; one bad claim shouldn't kill the run
                row["error"] = repr(e)
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            if "error" in row:
                print(f"#{row['id']}: ERROR {row['error']}")
                continue
            n = row["new"]
            line = f"#{row['id']:>4} deep={row['deep'] or '—':<15} new={n['consistency']:<15} "
            line += f"new {row['reform_s']:.1f}+{n['search_s']:.1f}+{n['synth_s']:.1f}s"
            if not NEW_ONLY:
                o = row["old"]
                line += (f" | old={o['consistency']} {o['search_s'] + o['synth_s']:.1f}s"
                         f" (lite reform {row['reform_lite_s']:.1f}s)")
            print(line)

    ok = [r for r in rows if "error" not in r]
    if not ok:
        return

    def avg(xs):
        return sum(xs) / len(xs)

    print("\n--- Summary ---")
    print(f"claims: {len(ok)}/{len(rows)}")
    variants = ("new",) if NEW_ONLY else ("old", "new")
    for v in variants:
        print(f"{v}: search {avg([r[v]['search_s'] for r in ok]):.2f}s  synth {avg([r[v]['synth_s'] for r in ok]):.2f}s")
    print(f"reformulation: {avg([r['reform_s'] for r in ok]):.2f}s", end="")
    print("" if NEW_ONLY else f"  vs  lite {avg([r['reform_lite_s'] for r in ok]):.2f}s")
    for v in variants:
        dist = {}
        for r in ok:
            dist[r[v]["consistency"]] = dist.get(r[v]["consistency"], 0) + 1
        agree = sum(1 for r in ok if r["deep"] and r[v]["consistency"] == r["deep"])
        print(f"{v}: {dist}  agrees with deep checker: {agree}/{sum(1 for r in ok if r['deep'])}")


if __name__ == "__main__":
    asyncio.run(main())
