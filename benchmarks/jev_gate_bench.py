"""
Jev claim-gate benchmark.

Tests TypeSafe's Jev decision model (typesafe/jev-1.13.0 via Requesty) as a
per-sentence claim gate for the live fast lane: split text into sentences, ask Jev a
single yes/no ("noul") question per sentence — "contains a verifiable factual claim?" —
and read back a calibrated probability. This is the SG-7 "JevGate" pre-filter idea.

Findings (21.09.2026, jev-1.13.0):
- Number-free real claims (NATO membership, "Merkel war Kanzlerin") score ~0.97-0.99,
  so Jev judges *checkability*, not digit presence.
- Clear opinions score ~0.04-0.18.
- Genuine borderline sentences ("In Deutschland wird zu wenig gearbeitet" 0.54,
  "innovativste Land Europas" 0.63) cluster around 0.5 — honest, calibrated uncertainty.
- ~290 ms/sentence.
=> Use a threshold BAND, not a hard 0.5 cut:  p>=0.85 auto-check, p<=0.30 skip,
   0.30-0.85 grey zone (skip conservatively, or route to a stronger LLM).

Run: REQUESTY_API_KEY=... uv run python benchmarks/jev_gate_bench.py
"""

import os
import re
import json
import time

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

API_KEY = os.getenv("REQUESTY_API_KEY")
BASE_URL = os.getenv("REQUESTY_BASE_URL", "https://router.requesty.ai/v1")
MODEL = os.getenv("JEV_MODEL", "typesafe/jev-1.13.0")
CHECK_HI = float(os.getenv("JEV_CHECK_THRESHOLD", "0.85"))  # >= -> auto-check
SKIP_LO = float(os.getenv("JEV_SKIP_THRESHOLD", "0.30"))    # <= -> skip

if not API_KEY:
    raise SystemExit("REQUESTY_API_KEY fehlt (in .env eintragen oder inline setzen).")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# The sentence is the "state" (message content); this is the judgment ("noul" = yes prob).
QUESTION = {
    "claim": {
        "type": "noul",
        "instructions": "Enthält dieser Satz eine überprüfbare Tatsachenbehauptung, die man faktenchecken könnte?",
        "criteria": {
            "true": "Überprüfbarer Tatsachenkern: Zahl, Statistik, Datum, historisches oder aktuelles Faktum, konkrete Aussage über die Realität (wer/was/wann).",
            "false": "Reine Meinung, Wertung, Absicht, Forderung, Frage, Begrüßung oder Floskel ohne überprüfbaren Tatsachenkern.",
        },
    }
}

# Hard set: checkable claims WITHOUT numbers + quasi-factual opinions. TRICKY = grey zone.
TEXT = (
    "In Deutschland wird zu wenig gearbeitet. "
    "Deutschland ist Mitglied der NATO. "
    "Die Energiewende ist gescheitert. "
    "Die Zugspitze ist der höchste Berg Deutschlands. "
    "Bürgergeld-Empfänger wollen gar nicht arbeiten. "
    "Russland hat die Ukraine angegriffen. "
    "Die Steuern in Deutschland sind viel zu hoch. "
    "Frauen verdienen in Deutschland im Schnitt weniger als Männer. "
    "Deutschland ist das innovativste Land Europas. "
    "Der Bundestag hat das Heizungsgesetz beschlossen. "
    "Wir sollten das Renteneintrittsalter anheben. "
    "Angela Merkel war Bundeskanzlerin."
)
EXPECTED = [False, True, False, True, False, True, False, True, False, True, False, True]
TRICKY = {0, 2, 4, 7, 8}


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def _extract_prob(value) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for k in ("noul", "value", "probability", "prob", "yes"):
            if isinstance(value.get(k), (int, float)):
                return float(value[k])
    return None


def ask_jev(sentence: str) -> tuple[float | None, str, float]:
    t0 = time.time()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": sentence}],
        response_format={"type": "questions", "questions": QUESTION},
    )
    dt = time.time() - t0
    raw = resp.choices[0].message.content or ""
    prob = None
    try:
        prob = _extract_prob(json.loads(raw).get("claim"))
    except Exception:
        pass
    return prob, raw.strip(), dt


def band(p: float | None) -> str:
    if p is None:
        return "?"
    if p >= CHECK_HI:
        return "CHECK"
    if p <= SKIP_LO:
        return "skip"
    return "grau"


def main():
    sentences = split_sentences(TEXT)
    print(f"Modell: {MODEL}  Band: check>={CHECK_HI}  skip<={SKIP_LO}\n{len(sentences)} Sätze\n")
    total = 0.0
    for i, s in enumerate(sentences):
        prob, raw, dt = ask_jev(s)
        total += dt
        exp = {True: "claim", False: "kein", None: "?"}[EXPECTED[i] if i < len(EXPECTED) else None]
        tag = " «Grenzfall»" if i in TRICKY else ""
        p_str = "  ?  " if prob is None else f"{prob:.2f}"
        print(f"  erwartet={exp:5} p={p_str} [{band(prob):5}] ({dt*1000:4.0f}ms)  {s}{tag}")
    print(f"\nØ Latenz: {total/max(len(sentences),1)*1000:.0f}ms/Satz")


if __name__ == "__main__":
    main()
