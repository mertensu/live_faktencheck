"""
Does looking inside the PDFs help? Reuses the saved hits of primary.jsonl (no new searches).

Per claim: A = live hits of queries a–e, judged as live (snippet cut at FAST_SNIPPET_CHARS).
B = same hits, but every PDF hit additionally gets the chunks Tavily Extract returns for the
claim (query reranking, up to CHUNKS chunks of ≤500 chars per source). Same judge.

    DATA=primary.jsonl OUT=extract.jsonl python benchmarks/extract_bench.py
"""

import os
import sys
import json
import time
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tavily import AsyncTavilyClient  # noqa: E402

from backend.services.fast_fact_checker import FastFactChecker, _is_noise, _url_key  # noqa: E402
from backend.services.trusted_domains import source_tier  # noqa: E402

DATA = os.getenv("DATA", "primary.jsonl")
CLAIMS = os.getenv("CLAIMS", "claims_primary.json")
OUT = os.getenv("OUT", "extract.jsonl")
CHUNKS = int(os.getenv("CHUNKS", "5"))
MAX_PDFS = int(os.getenv("MAX_PDFS", "10"))
EXTRA_CHARS = int(os.getenv("EXTRA_CHARS", "2500"))


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


def _format(hits, cut, extra):
    lines = []
    for r in hits:
        url = r.get("url", "")
        content = (r.get("content") or "")[:cut]
        if url in extra:
            content += " [Weitere Stellen im Dokument:] " + extra[url][:EXTRA_CHARS]
        lines.append(f"- [{source_tier(url)[1]}] {r.get('title', '')} ({url}): {content}")
    return "\n".join(lines) or "(keine Suchergebnisse)"


def _message(c):
    return (f"Kontext der Sendung: {c.get('context') or '—'}\n"
            f"Sendedatum: {c.get('episode_date') or '—'}\n"
            f"Sprecher: {c.get('speaker') or '—'}\n"
            f"Behauptung: {c['claim']}")


async def _judge(checker, c, hits, extra):
    t0 = time.perf_counter()
    try:
        out = (await checker.agent.run(_message(c) + "\n\nSuchergebnisse aus vertrauenswürdigen Quellen:\n"
                                       + _format(hits, checker.snippet_chars, extra))).output
        urls = {r.get("url") for r in hits}
        res = {"consistency": out.consistency, "evidence": out.evidence,
               "sources": [s.url for s in out.sources if s.url in urls]}
    except Exception as e:
        res = {"error": repr(e)}
    res["judge_s"] = round(time.perf_counter() - t0, 2)
    return res


async def main():
    rows = [json.loads(line) for line in open(DATA)]
    claims = {c["id"]: c for c in json.loads(Path(CLAIMS).read_text())}
    checker = FastFactChecker()
    client = AsyncTavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    total_urls = 0
    with open(OUT, "w") as f:
        for r in rows:
            c = claims[r["id"]]
            hits = _merge(r["hits_per_query"][:5])
            pdfs = [h["url"] for h in hits if ".pdf" in (h.get("url") or "").lower()][:MAX_PDFS]
            extra, ext_s, failed = {}, 0.0, []
            if pdfs:
                t0 = time.perf_counter()
                try:
                    resp = await client.extract(urls=pdfs, query=r.get("reformulated") or c["claim"],
                                                chunks_per_source=CHUNKS, extract_depth="basic",
                                                format="text", include_usage=True)
                    for item in resp.get("results", []) or []:
                        extra[item.get("url")] = item.get("raw_content") or ""
                    failed = [x.get("url") for x in resp.get("failed_results", []) or []]
                    usage = resp.get("usage")
                except Exception as e:
                    failed, usage = [repr(e)], None
                ext_s = round(time.perf_counter() - t0, 2)
                total_urls += len(extra)
            else:
                usage = None
            a, b = await asyncio.gather(_judge(checker, c, hits, {}), _judge(checker, c, hits, extra))
            row = {"id": r["id"], "claim": c["claim"], "deep": r["deep"], "live_before": r["A"].get("consistency"),
                   "n_hits": len(hits), "pdfs": pdfs, "extracted": {u: v[:3000] for u, v in extra.items()},
                   "failed": failed, "extract_s": ext_s, "usage": usage, "A": a, "B": b}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"#{r['id']:>3} deep={r['deep']:<8} A={a.get('consistency', 'ERR'):<15} B={b.get('consistency', 'ERR'):<15}"
                  f" PDFs {len(pdfs)} extrahiert {len(extra)} fehlg. {len(failed)} {ext_s}s usage={usage}", flush=True)
    print(f"extrahierte URLs gesamt: {total_urls} (≈ {total_urls / 5:.1f} Credits)")


if __name__ == "__main__":
    asyncio.run(main())
