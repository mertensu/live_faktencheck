"""
A/B of the reformulator's query angles, with the PR #19 fast check (read deeper on undecided).

A = live angles (… c "Entwicklung" …): queries and hits reused from primary.jsonl (no new
    search), judged with PR #19 logic (judge → if undecided, Extract on PDFs/research hits → judge).
B = PR #19 angles (c "Studie", e "Entwicklung/Gegenposition"): new reformulation, 5 searches,
    same PR #19 logic. Mirrors live: the reformulated claim is what the checker sees.

    DATA=primary.jsonl CLAIMS=claims_primary.json OUT=studie.jsonl python benchmarks/studie_bench.py
"""

import os
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.services.fast_fact_checker as ffc  # noqa: E402
from backend.services.claim_extraction import ClaimExtractor  # noqa: E402
from backend.services.fast_fact_checker import FastFactChecker, _is_noise, _url_key  # noqa: E402
from backend.services.trusted_domains import source_tier  # noqa: E402

DATA = os.getenv("DATA", "primary.jsonl")
CLAIMS = os.getenv("CLAIMS", "claims_primary.json")
OUT = os.getenv("OUT", "studie.jsonl")
BUDGET = int(os.getenv("BUDGET", "85"))
UNDECIDED = ("unklar", "keine Datenlage")

state = {"search": 0, "extract_urls": 0}
_search, _extract = ffc.tavily_search, ffc.tavily_extract


async def counted_search(q, **kw):
    if state["search"] + state["extract_urls"] / 5 >= BUDGET:
        return {"results": []}
    state["search"] += 1
    return await _search(q, **kw)


async def counted_extract(urls, query):
    out = await _extract(urls, query=query)
    state["extract_urls"] += len(out)
    return out


ffc.tavily_search, ffc.tavily_extract = counted_search, counted_extract


def _merge(per_query):
    seen, merged = set(), []
    for res in per_query:
        for item in res:
            url = item.get("url") or ""
            if _is_noise(url):
                continue
            key = _url_key(url)
            if key and key in seen:
                continue
            seen.add(key)
            merged.append(item)
    merged.sort(key=lambda r: source_tier(r.get("url", ""))[0])
    return merged


async def _check(checker, c, claim, results):
    """PR #19 check on given hits: judge; if undecided, read deeper and judge again."""
    header = (f"Kontext der Sendung: {c.get('context') or '—'}\n"
              f"Sendedatum: {c.get('episode_date') or '—'}\n"
              f"Sprecher: {c.get('speaker') or '—'}\n"
              f"Behauptung: {claim}")
    t0 = time.perf_counter()
    first = await checker._judge(header, results)
    out = {"first": first.get("consistency"), "first_evidence": first.get("evidence"),
           "judge1_s": round(time.perf_counter() - t0, 2), "read": 0, "read_s": 0.0}
    final = first
    if first.get("consistency") in UNDECIDED:
        t1 = time.perf_counter()
        extra = await checker._read_deeper(claim, results)
        out["read_s"] = round(time.perf_counter() - t1, 2)
        out["read"] = len(extra)
        if extra:
            t2 = time.perf_counter()
            final = await checker._judge(header, results, extra)
            out["judge2_s"] = round(time.perf_counter() - t2, 2)
    out.update(consistency=final.get("consistency"), evidence=final.get("evidence"),
               sources=[s.get("url") for s in final.get("sources", [])])
    return out


async def main():
    rows = [json.loads(line) for line in open(DATA)]
    claims = {c["id"]: c for c in json.loads(Path(CLAIMS).read_text())}
    checker = FastFactChecker()
    extractor = ClaimExtractor()
    with open(OUT, "w") as f:
        for r in rows:
            c = claims[r["id"]]
            guests = c.get("guests") or []
            if isinstance(guests, str):
                guests = json.loads(guests or "[]")
            # A: live angles, saved hits.
            hits_a = _merge(r["hits_per_query"][:5])
            a = await _check(checker, c, r.get("reformulated") or c["claim"], hits_a)
            a["queries"] = r["queries"]
            # B: PR #19 angles, fresh reformulation and search.
            t0 = time.perf_counter()
            ref = await extractor.reformulate_claim_async(c["claim"], speaker=c.get("speaker", ""),
                                                          guests=guests, context=c.get("context", ""))
            reform_s = round(time.perf_counter() - t0, 2)
            t1 = time.perf_counter()
            hits_b = await checker._gather_evidence(ref.claim, list(ref.search_queries))
            search_s = round(time.perf_counter() - t1, 2)
            b = await _check(checker, c, ref.claim, hits_b)
            b.update(queries=list(ref.search_queries), reformulated=ref.claim, reform_s=reform_s,
                     search_s=search_s,
                     hits=[{"url": h.get("url"), "title": h.get("title"),
                            "content": (h.get("content") or "")[:2000]} for h in hits_b])
            row = {"id": r["id"], "claim": c["claim"], "deep": r["deep"], "A": a, "B": b,
                   "credits": round(state["search"] + state["extract_urls"] / 5, 1)}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"#{r['id']:>3} deep={r['deep']:<8} A={a['first']}->{a['consistency']} "
                  f"B={b['first']}->{b['consistency']}  Credits {row['credits']}", flush=True)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
