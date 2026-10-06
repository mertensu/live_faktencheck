"""Run one claim through the live lane (reformulator → fast check incl. read deeper) and log
whether a target document is found and what is read from it.

    CLAIM=... SPEAKER=... CONTEXT=... TARGET=2100601 RUNS=2 python benchmarks/single_claim.py
"""
import os
import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.services.fast_fact_checker as ffc  # noqa: E402
from backend.services.claim_extraction import ClaimExtractor  # noqa: E402
from backend.services.fast_fact_checker import FastFactChecker  # noqa: E402

CLAIM, SPEAKER, CONTEXT = os.environ["CLAIM"], os.getenv("SPEAKER", ""), os.getenv("CONTEXT", "")
TARGET = os.getenv("TARGET", "")
RUNS = int(os.getenv("RUNS", "2"))
log = {}
_extract = ffc.tavily_extract


async def logged_extract(urls, query):
    out = await _extract(urls, query=query)
    log["extract_urls"], log["extracted"] = urls, out
    return out
ffc.tavily_extract = logged_extract


async def main():
    ex, checker = ClaimExtractor(), FastFactChecker()
    rows = []
    for run in range(RUNS):
        log.clear()
        r = await ex.reformulate_claim_async(CLAIM, speaker=SPEAKER, guests=[SPEAKER], context=CONTEXT)
        hits = await checker._gather_evidence(r.claim, list(r.search_queries))
        header = f"Kontext der Sendung: {CONTEXT or '—'}\nSendedatum: —\nSprecher: {SPEAKER}\nBehauptung: {r.claim}"
        first = await checker._judge(header, hits)
        final, extra = first, {}
        if first.get("consistency") in ("unklar", "keine Datenlage"):
            extra = await checker._read_deeper(r.claim, hits)
            if extra:
                final = await checker._judge(header, hits, extra)
        tgt = [h for h in hits if TARGET and TARGET in (h.get("url") or "")]
        row = {"run": run, "reformulated": r.claim, "queries": list(r.search_queries),
               "hits": [{"url": h.get("url"), "title": h.get("title"), "content": (h.get("content") or "")[:1500]} for h in hits],
               "target_found": bool(tgt), "target_snippet": tgt[0].get("content", "")[:1500] if tgt else "",
               "first": first, "read_urls": log.get("extract_urls", []),
               "target_read": {u: t for u, t in extra.items() if TARGET in u}, "final": final}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
    Path("/work/single.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n")


asyncio.run(main())
