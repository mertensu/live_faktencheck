"""A/B: press as hints (FAST_PRESS_HINTS). Shared reformulation, base searches and press search;
A = live flow without press, B = press hits in a separate 'hints, not evidence' block.
Logs named documents, follow-up hits, first/final verdict, and whether press leaks into sources."""
import json
import asyncio
from pathlib import Path

from backend.services.claim_extraction import ClaimExtractor
from backend.services.fast_fact_checker import FastFactChecker
from backend.services.trusted_domains import PRESS_DOMAINS


async def flow(c, header, claim, results, press):
    first = await c._judge(header, results, press=press)
    titles = first.get("referenced_documents") or []
    docs = await c._follow_documents(titles, results) if titles else []
    to_read = [d["url"] for d in docs]
    if first.get("consistency") in ("unklar", "keine Datenlage"):
        to_read += [r["url"] for r in results if r.get("url") and c._readable(r["url"])]
    extra = await c._read(claim, to_read) if to_read else {}
    final = await c._judge(header, results + docs, extra) if (docs or extra) else first
    srcs = [s.get("url") for s in final.get("sources", [])]
    return {"first": first.get("consistency"), "first_evidence": first.get("evidence"), "titles": titles,
            "docs": [{"url": d.get("url"), "title": d.get("title")} for d in docs], "read": list(extra),
            "final": final.get("consistency"), "evidence": final.get("evidence"), "sources": srcs,
            "press_in_sources": any(p in (u or "") for u in srcs for p in PRESS_DOMAINS)}


async def main():
    c, ex = FastFactChecker(), ClaimExtractor()
    out = open("/work/press.jsonl", "w")
    for cl in json.loads(Path("/work/claims_press.json").read_text()):
        guests = cl.get("guests") or []
        guests = json.loads(guests) if isinstance(guests, str) else guests
        r = await ex.reformulate_claim_async(cl["claim"], speaker=cl.get("speaker", ""), guests=guests,
                                             context=cl.get("context", ""))
        results, press = await asyncio.gather(c._gather_evidence(r.claim, list(r.search_queries)), c._press(r.claim))
        header = (f"Kontext der Sendung: {cl.get('context') or '—'}\nSendedatum: {cl.get('episode_date') or '—'}\n"
                  f"Sprecher: {cl.get('speaker') or '—'}\nBehauptung: {r.claim}")
        a, b = await asyncio.gather(flow(c, header, r.claim, results, []), flow(c, header, r.claim, results, press))
        row = {"id": cl["id"], "deep": cl.get("deep_consistency", ""), "claim": r.claim,
               "press": [{"url": p.get("url"), "title": p.get("title"), "content": (p.get("content") or "")[:800]} for p in press],
               "A": a, "B": b}
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        out.flush()

asyncio.run(main())
