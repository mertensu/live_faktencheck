"""Follow referenced documents (new fast check): logs which documents the first verdict names,
what the title search finds, what is read, and first vs. final verdict.

Part 1: GRIMM_RUNS full live runs of one claim (reformulator + search + check).
Part 2: stored hits of primary.jsonl (12 claims with deep reference), no base searches.
"""
import os
import sys
import json
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.claim_extraction import ClaimExtractor  # noqa: E402
from backend.services.fast_fact_checker import FastFactChecker, _is_noise, _url_key  # noqa: E402
from backend.services.trusted_domains import source_tier  # noqa: E402

trace = {}


def instrument(c):
    judge, follow, read = c._judge, c._follow_documents, c._read

    async def j(header, results, extra=None):
        out = await judge(header, results, extra)
        trace.setdefault("verdicts", []).append({k: out.get(k) for k in ("consistency", "evidence", "referenced_documents")}
                                                 | {"sources": [s.get("url") for s in out.get("sources", [])]})
        return out

    async def f(titles, results):
        out = await follow(titles, results)
        trace["followed"] = [{"url": d.get("url"), "title": d.get("title")} for d in out]
        return out

    async def r(claim, urls):
        out = await read(claim, urls)
        trace["read"] = {u: t[:1500] for u, t in out.items()}
        return out
    c._judge, c._follow_documents, c._read = j, f, r


def _merge(per_query):
    seen, merged = set(), []
    for res in per_query:
        for item in res:
            url = item.get("url") or ""
            if _is_noise(url) or _url_key(url) in seen:
                continue
            seen.add(_url_key(url))
            merged.append(item)
    merged.sort(key=lambda r: source_tier(r.get("url", ""))[0])
    return merged


async def main():
    c = FastFactChecker()
    instrument(c)
    out = open("/work/follow.jsonl", "w")
    ex = ClaimExtractor()
    claim = "2029 fressen Soziales, Zinsen und Verteidigung den gesamten Bundeshaushalt auf."
    for run in range(int(os.getenv("GRIMM_RUNS", "2"))):
        trace.clear()
        r = await ex.reformulate_claim_async(claim, speaker="Veronika Grimm", guests=["Veronika Grimm"],
                                             context="Bundeshaushalt, Staatsfinanzen und Finanzplanung bis 2029")
        res = await c.check_claim_async(speaker="Veronika Grimm", claim=r.claim,
                                        context="Bundeshaushalt, Staatsfinanzen und Finanzplanung bis 2029",
                                        queries=list(r.search_queries))
        row = {"part": "grimm", "run": run, "claim": r.claim, "final": res.get("consistency"), **trace}
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        out.flush()
    claims = {x["id"]: x for x in json.loads(Path("/work/claims_primary.json").read_text())}
    for line in open("/work/primary.jsonl"):
        p = json.loads(line)
        cl = claims[p["id"]]
        trace.clear()
        hits = _merge(p["hits_per_query"][:5])
        header = (f"Kontext der Sendung: {cl.get('context') or '—'}\nSendedatum: {cl.get('episode_date') or '—'}\n"
                  f"Sprecher: {cl.get('speaker') or '—'}\nBehauptung: {p['reformulated']}")
        # Same flow as check_claim_async, on stored hits.
        first = await c._judge(header, hits)
        titles = first.get("referenced_documents") or []
        docs = await c._follow_documents(titles, hits) if titles else []
        to_read = [d["url"] for d in docs]
        if first.get("consistency") in ("unklar", "keine Datenlage"):
            to_read += [h["url"] for h in hits if c._readable(h["url"])]
        extra = await c._read(p["reformulated"], to_read) if to_read else {}
        final = await c._judge(header, hits + docs, extra) if (docs or extra) else first
        row = {"part": "deep12", "id": p["id"], "deep": p["deep"], "claim": p["reformulated"],
               "final": final.get("consistency"), **trace}
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
        out.flush()

asyncio.run(main())
