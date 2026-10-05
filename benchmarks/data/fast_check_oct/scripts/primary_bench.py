"""
A/B: replace the reformulator's "Entwicklung" query with a primary-source query.

Per claim, one reformulator run (live agent and prompt, plus one extra output field
``primary_query``) yields the 5 live queries a–e and a 6th query f. All 6 are searched once
(Tavily basic, in parallel). Then the live judge rules twice on merged hits:
  A = queries a, b, c, d, e   (live)
  B = queries a, b, d, e, f   (c "Entwicklung" replaced by f "Primärquelle")
So A and B differ only in one query. Every query's full hits are saved, so judge variants can
later be tested offline on the same evidence. Also logs a plausibility flag: a confident
level ('hoch'/'niedrig') with no sources or with "missing" wording in the evidence.

    CLAIMS=claims.json OUT=primary.jsonl python benchmarks/primary_bench.py
"""

import os
import re
import sys
import json
import time
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import Field  # noqa: E402

from pydantic_ai import Agent  # noqa: E402

from backend.services.claim_extraction import ClaimExtractor, ReformulatedClaim  # noqa: E402
from backend.utils import load_prompt  # noqa: E402
from backend.services.fast_fact_checker import FastFactChecker, _is_noise, _url_key  # noqa: E402
from backend.services.search import tavily_search  # noqa: E402
from backend.services.trusted_domains import source_tier  # noqa: E402

CLAIMS = os.getenv("CLAIMS", "claims.json")
OUT = os.getenv("OUT", "primary.jsonl")
BUDGET = int(os.getenv("BUDGET", "80"))

PRIMARY_RULE = """

Zusätzlich (``primary_query``): eine sechste Anfrage nach der **Primärquelle** — wer die Zahl
oder Aussage ursprünglich veröffentlicht hat oder worauf sich die Behauptung stützt (Partei,
Verband, Behörde, Studie, Programm; bei einer eigenen Zahl des Sprechers: Sprecher oder Partei),
dazu die zentrale Zahl oder Wortfolge der Behauptung **wörtlich in Anführungszeichen**.
Beispiel: Linke Vermögensteuer "147 Milliarden". Gibt es keine Zahl, die prägnanteste
Wortfolge der Behauptung in Anführungszeichen."""


class ReformulatedWithPrimary(ReformulatedClaim):
    primary_query: str = Field(
        default="",
        description="Sechste Anfrage nach der Primärquelle: Urheber (Partei, Verband, Behörde, "
                    "Studie, ggf. Sprecher) plus die zentrale Zahl oder Wortfolge wörtlich in "
                    "Anführungszeichen.",
    )


MISSING = re.compile(r"fehl|keine[nrs]? (konkreten |empirischen |vergleichenden )?(Belege|Daten|Angaben|Zahlen)|"
                     r"nicht belegt|nicht hervor|liegen keine|lässt sich .* nicht", re.IGNORECASE)

state = {"credits": 0}


def _message(c: dict) -> str:
    return (f"Kontext der Sendung: {c.get('context') or '—'}\n"
            f"Sendedatum: {c.get('episode_date') or '—'}\n"
            f"Sprecher: {c.get('speaker') or '—'}\n"
            f"Behauptung: {c['claim']}")


def _merge(per_query: list[list[dict]]) -> list[dict]:
    """Same filtering as FastFactChecker._gather_evidence: noise out, dedupe, tier sort."""
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


async def _search(q: str) -> list[dict]:
    if not q or state["credits"] >= BUDGET:
        return []
    state["credits"] += 1
    try:
        return (await tavily_search(q, search_depth="basic")).get("results", []) or []
    except Exception:
        return []


async def _judge(checker: FastFactChecker, c: dict, hits: list[dict]) -> dict:
    t0 = time.perf_counter()
    try:
        out = (await checker.agent.run(
            _message(c) + "\n\nSuchergebnisse aus vertrauenswürdigen Quellen:\n" + checker._format_evidence(hits))).output
        urls = {r.get("url") for r in hits}
        res = {"consistency": out.consistency, "evidence": out.evidence,
               "sources": [s.url for s in out.sources if s.url in urls]}
        res["plausibility_flag"] = (res["consistency"] in ("hoch", "niedrig")
                                    and (not res["sources"] or bool(MISSING.search(res["evidence"]))))
    except Exception as e:
        res = {"error": repr(e)}
    res["judge_s"] = round(time.perf_counter() - t0, 2)
    res["n_hits"] = len(hits)
    return res


async def main() -> None:
    claims = json.loads(Path(CLAIMS).read_text())
    checker = FastFactChecker()
    extractor = ClaimExtractor()
    # Same agent, model and prompt as live; only the output gains ``primary_query``.
    reform = extractor.reformulator
    extractor.reformulator = Agent(
        reform.model, output_type=ReformulatedWithPrimary,
        instructions=load_prompt("claim_reformulation.md") + PRIMARY_RULE,
        model_settings=reform.model_settings,
    )

    with open(OUT, "w") as f:
        for c in claims:
            guests = c.get("guests") or []
            if isinstance(guests, str):
                guests = json.loads(guests or "[]")
            t0 = time.perf_counter()
            r = await extractor.reformulate_claim_async(c["claim"], speaker=c.get("speaker", ""),
                                                        guests=guests, context=c.get("context", ""))
            reform_s = round(time.perf_counter() - t0, 2)
            qs = (list(r.search_queries) + [""] * 5)[:5]
            primary = (getattr(r, "primary_query", "") or "").strip()
            t1 = time.perf_counter()
            per = await asyncio.gather(*(_search(q) for q in qs + [primary]))
            search_s = round(time.perf_counter() - t1, 2)
            hits_a = _merge([per[0], per[1], per[2], per[3], per[4]])
            hits_b = _merge([per[0], per[1], per[3], per[4], per[5]])
            a, b = await asyncio.gather(_judge(checker, c, hits_a), _judge(checker, c, hits_b))
            keys_a = {_url_key(h.get("url") or "") for h in hits_a}
            only_b = [h.get("url") for h in hits_b if _url_key(h.get("url") or "") not in keys_a]
            b["cites_primary_hit"] = any(u in only_b for u in b.get("sources", []))
            row = {
                "id": c.get("id"), "claim": c["claim"], "reformulated": r.claim,
                "deep": c.get("deep_consistency", ""), "queries": qs, "primary_query": primary,
                "reform_s": reform_s, "search_s": search_s, "A": a, "B": b, "only_in_B": only_b,
                "hits_per_query": [[{"url": h.get("url"), "title": h.get("title"),
                                     "content": (h.get("content") or "")[:2000]} for h in res] for res in per],
                "credits_so_far": state["credits"],
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"#{row['id']:>3} deep={row['deep']:<8} A={a.get('consistency', 'ERR'):<15} "
                  f"B={b.get('consistency', 'ERR'):<15} nur-B-Treffer={len(only_b)} "
                  f"zitiert={b.get('cites_primary_hit')}  f: {primary}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
