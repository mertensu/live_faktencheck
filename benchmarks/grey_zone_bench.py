"""
Grey-zone benchmark for the Jev gate.

Scores each sentence with Jev, shows where it lands (hit / grey / skip) and, for the grey
ones, asks the grey-zone judge (``ClaimExtractor.judge_grey_zone_async``) for its second
opinion — the same path ``JevGate`` takes live. With ``--all`` the judge sees every
sentence, so its verdict on the opinions shows too.

SHOULD_PASS are the talk-show sentences Jev dropped in the Atalay test (02.10.2026,
session bbc8575b396f); SHOULD_SKIP are opinions, demands and filler that must stay out.

Run: uv run python -m benchmarks.grey_zone_bench [--all] [--runs N]
(needs REQUESTY_API_KEY and GEMINI_API_KEY in .env; no Tavily calls)
"""

import argparse
import asyncio
import os
import time

from dotenv import load_dotenv

load_dotenv()

from backend.services.claim_extraction import ClaimExtractor  # noqa: E402
from backend.services.gate import JevGate, JevScorer  # noqa: E402

SHOULD_PASS = [
    "Steuererhöhungen führen zu keinem Wachstum.",
    "Wir befinden uns in einer Situation wirtschaftlicher Stagnation.",
    "Der Staat gibt immer mehr Geld aus.",
    "Der Staat nimmt den Bürgern immer mehr Geld weg.",
    "Deutschland ist ein Höchststeuerland.",
]

SHOULD_SKIP = [
    "Das finde ich zutiefst ungerecht.",
    "Wir müssen die Schuldenbremse endlich reformieren.",
    "Ich glaube, dass die Leute das Vertrauen in die Politik verloren haben.",
    "Das ist eine Frage des Anstands.",
    "Herr Amthor, darauf will ich gleich noch mal kommen.",
    "Wir werden das nach der Wahl ändern.",
    "Da bin ich ganz anderer Meinung als Sie.",
]

CONTEXT = "Talkshow zu Steuern, Staatsfinanzen und Vermögensteuer"


async def run(extractor: ClaimExtractor, gate: JevGate, all_sentences: bool) -> tuple[int, int]:
    rows = [(s, True) for s in SHOULD_PASS] + [(s, False) for s in SHOULD_SKIP]
    scores = await asyncio.gather(*(gate._scorer.score(s) for s, _ in rows))

    async def judge(sentence: str) -> tuple[bool, float]:
        t = time.perf_counter()
        yes = await extractor.judge_grey_zone_async(sentence, context=CONTEXT)
        return yes, time.perf_counter() - t

    verdicts = [gate._verdict(sc) for sc in scores]
    asks = [all_sentences or v == "grey" for v in verdicts]
    judged = await asyncio.gather(*(judge(s) if ask else asyncio.sleep(0, (None, 0.0))
                                    for (s, _), ask in zip(rows, asks)))
    right = 0
    for (sentence, want), sc, verdict, (yes, dt) in zip(rows, scores, verdicts, judged):
        passed = verdict == "CHECK" or (verdict == "grey" and yes)
        right += passed == want
        judge_str = "     " if yes is None else f"{'ja' if yes else 'nein':4} {dt:4.1f}s"
        print(f"{'✓' if passed == want else '✗'} soll {'durch' if want else 'raus '} | "
              f"p={sc.check if sc.check is not None else float('nan'):.2f} "
              f"imp={sc.important if sc.important is not None else float('nan'):.2f} "
              f"{verdict:9} | LLM {judge_str} | {sentence}")
    return right, len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="ask the judge on every sentence")
    ap.add_argument("--runs", type=int, default=1)
    args = ap.parse_args()
    print(f"judge model: {os.getenv('GEMINI_MODEL_GREY_ZONE', 'gemini-3.5-flash-lite')}")
    asyncio.run(runs(args.all, args.runs))


async def runs(all_sentences: bool, n: int) -> None:
    extractor = ClaimExtractor()
    gate = JevGate(extractor, JevScorer())
    for i in range(n):
        right, total = await run(extractor, gate, all_sentences)
        print(f"--- Lauf {i + 1}: {right}/{total} richtig\n")


if __name__ == "__main__":
    main()
