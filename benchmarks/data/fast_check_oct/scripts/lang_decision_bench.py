"""Does the reformulator (PR #19 prompt) write the yardstick query in English exactly for
international comparisons? Reformulation only — no search, no Tavily credits.

    CLAIMS=claims_lang.json OUT=lang.jsonl RUNS=2 python benchmarks/lang_decision_bench.py
"""
import os
import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.claim_extraction import ClaimExtractor  # noqa: E402

CLAIMS = os.getenv("CLAIMS", "claims_lang.json")
OUT = os.getenv("OUT", "lang.jsonl")
RUNS = int(os.getenv("RUNS", "2"))


async def main():
    claims = json.loads(Path(CLAIMS).read_text())
    ex = ClaimExtractor()
    with open(OUT, "w") as f:
        for run in range(RUNS):
            async def one(c):
                guests = json.loads(c["guests"] or "[]")
                r = await ex.reformulate_claim_async(c["claim"], speaker=c["speaker"], guests=guests, context=c["context"])
                return {"run": run, "id": c["id"], "expect": c["expect"], "claim": c["claim"],
                        "reformulated": r.claim, "queries": list(r.search_queries)}
            rows = await asyncio.gather(*(one(c) for c in claims))
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"r{run} #{row['id']} [{row['expect']}] d: {row['queries'][3] if len(row['queries']) > 3 else '?'}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
