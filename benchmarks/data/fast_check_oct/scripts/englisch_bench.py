"""
A/B: the yardstick ("Maßstab") query in English for country/EU/international comparisons.

German queries never surfaced Eurostat (its releases are English); an English query hit the
right release at once. Per claim, one reformulator run (PR #19 prompt, plus one extra output
field ``yardstick_en``) yields queries a–e and the English yardstick query. All 6 are searched
once. Then the PR #19 check (judge → if undecided, read deeper → judge) runs twice:
  A = a, b, c, d, e            (live)
  B = a, b, c, yardstick_en, e (d replaced by its English version)

    CLAIMS=claims.json OUT=englisch.jsonl python benchmarks/englisch_bench.py
"""

import os
import sys
import json
import time
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import Field  # noqa: E402
from pydantic_ai import Agent  # noqa: E402

import backend.services.fast_fact_checker as ffc  # noqa: E402
from backend.services.claim_extraction import ClaimExtractor, ReformulatedClaim  # noqa: E402
from backend.services.fast_fact_checker import FastFactChecker, _is_noise, _url_key  # noqa: E402
from backend.services.search import tavily_search  # noqa: E402
from backend.services.trusted_domains import source_tier  # noqa: E402
from backend.utils import load_prompt  # noqa: E402

CLAIMS = os.getenv("CLAIMS", "claims.json")
OUT = os.getenv("OUT", "englisch.jsonl")
BUDGET = int(os.getenv("BUDGET", "55"))
UNDECIDED = ("unklar", "keine Datenlage")

ENGLISH_RULE = """

Zusätzlich (``yardstick_en``): die Maßstab-Anfrage (d) noch einmal **auf Englisch**, mit dem
englischen Fachbegriff, unter dem internationale Statistiken (Eurostat, OECD, IEA, Weltbank)
veröffentlicht werden, und dem Zeitraum in deren Raster (z. B. „first half 2025“).
Beispiel: „Eurostat household electricity prices EU comparison first half 2025“."""


class ReformulatedWithEnglish(ReformulatedClaim):
    yardstick_en: str = Field(default="", description="Die Maßstab-Anfrage auf Englisch (internationale Statistik-Begriffe).")


state = {"credits": 0.0}
_extract = ffc.tavily_extract


async def counted_extract(urls, query):
    out = await _extract(urls, query=query)
    state["credits"] += len(out) / 5
    return out


ffc.tavily_extract = counted_extract


async def _search(q):
    if not q or state["credits"] >= BUDGET:
        return []
    state["credits"] += 1
    try:
        return (await tavily_search(q, search_depth="basic")).get("results", []) or []
    except Exception:
        return []


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
    header = (f"Kontext der Sendung: {c.get('context') or '—'}\n"
              f"Sendedatum: {c.get('episode_date') or '—'}\n"
              f"Sprecher: {c.get('speaker') or '—'}\n"
              f"Behauptung: {claim}")
    first = await checker._judge(header, results)
    out = {"first": first.get("consistency"), "read": 0}
    final = first
    if first.get("consistency") in UNDECIDED:
        extra = await checker._read_deeper(claim, results)
        out["read"] = len(extra)
        if extra:
            final = await checker._judge(header, results, extra)
    out.update(consistency=final.get("consistency"), evidence=final.get("evidence"),
               sources=[s.get("url") for s in final.get("sources", [])])
    return out


async def main():
    claims = json.loads(Path(CLAIMS).read_text())
    checker = FastFactChecker()
    extractor = ClaimExtractor()
    reform = extractor.reformulator
    extractor.reformulator = Agent(
        reform.model, output_type=ReformulatedWithEnglish,
        instructions=load_prompt("claim_reformulation.md") + ENGLISH_RULE,
        model_settings=reform.model_settings,
    )
    with open(OUT, "w") as f:
        for c in claims:
            guests = c.get("guests") or []
            if isinstance(guests, str):
                guests = json.loads(guests or "[]")
            r = await extractor.reformulate_claim_async(c["claim"], speaker=c.get("speaker", ""),
                                                        guests=guests, context=c.get("context", ""))
            qs = (list(r.search_queries) + [""] * 5)[:5]
            en = (getattr(r, "yardstick_en", "") or "").strip()
            t0 = time.perf_counter()
            per = await asyncio.gather(*(_search(q) for q in qs + [en]))
            search_s = round(time.perf_counter() - t0, 2)
            hits_a = _merge(per[:5])
            hits_b = _merge([per[0], per[1], per[2], per[5], per[4]])
            a, b = await asyncio.gather(_check(checker, c, r.claim, hits_a), _check(checker, c, r.claim, hits_b))
            keys_a = {_url_key(h.get("url") or "") for h in hits_a}
            only_b = [h.get("url") for h in hits_b if _url_key(h.get("url") or "") not in keys_a]
            b["cites_english_hit"] = any(u in only_b for u in b.get("sources", []))
            row = {"id": c.get("id"), "claim": c["claim"], "reformulated": r.claim,
                   "deep": c.get("deep_consistency", ""), "queries": qs, "yardstick_en": en,
                   "search_s": search_s, "A": a, "B": b, "only_in_B": only_b,
                   "hits_per_query": [[{"url": h.get("url"), "title": h.get("title"),
                                        "content": (h.get("content") or "")[:2000]} for h in res] for res in per],
                   "credits": round(state["credits"], 1)}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"#{row['id']} A={a['first']}->{a['consistency']} B={b['first']}->{b['consistency']} "
                  f"nur-B {len(only_b)} zitiert={b['cites_english_hit']} | d: {qs[3]} | en: {en}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
