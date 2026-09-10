"""
Qualitäts-Stresstest der Check-Stufe.

Fokus: Verdikt, Begründung und Belegdichte (Quellen) — NICHT Timing. Läuft
sequenziell, damit pro Claim sichtbar ist, ob der Agent auf 'advanced' eskaliert.
Modell = aktuelle .env (2.5-pro).

Die Claim-Menge ist bewusst gemischt: die SCHWEREN Claims zeigen, ob der Agent
eskaliert, wenn er soll — die LEICHTEN, ob er es unterlässt, wenn er nicht soll.
Nur der zweite Teil entscheidet über die Ersparnis: eskaliert er überall, ist
'agent' bloß eine teurere Voreinstellung als 'basic'.

Läuft lokal mit den eigenen Dev-Keys (kein SSH, kein Produktions-Kontingent):

    # Baseline (flache Suche, wie bisher live):
    QUAL_LABEL=basic TAVILY_SEARCH_DEPTH=basic uv run python benchmarks/quality_ab.py

    # Agent wählt fast/advanced — zweimal, um Rauschen von Wirkung zu trennen:
    QUAL_LABEL=agent RUNS=2 uv run python benchmarks/quality_ab.py

Achtung: echte API-Aufrufe (Gemini + Tavily), also echte Kosten. Ein Durchlauf
sind 9 Claims; `RUNS=2` verdoppelt das.

Die 'erwartet'-Notiz dient nur dem manuellen Abgleich — sie wird dem Modell NICHT
gezeigt.
"""
import asyncio
import os

from dotenv import load_dotenv

load_dotenv(os.getenv("FC_ENV", ".env"))

from backend.services.fact_checker import FactChecker  # noqa: E402
from backend.services import search as search_mod  # noqa: E402

LABEL = os.getenv("QUAL_LABEL", "?")
RUNS = int(os.getenv("RUNS", "1"))
CTX = "Bundespolitik Deutschland, aktuelle Wirtschafts- und Sozialdaten"
DATE = "September 2026"

# (Schwierigkeit, Sprecher, Behauptung, erwartete Tendenz — nur zur manuellen Kontrolle)
#
# schwer  — umstritten, mehrdeutig oder auf eine genaue Zahl angewiesen. Hier ist
#           eine Eskalation auf 'advanced' angemessen.
# leicht  — glatte, gut belegte Aussage, die eine Übersichtssuche klären sollte.
#           Eskaliert der Agent hier, verpufft die Ersparnis.
CLAIMS = [
    ("schwer", "B", "Der Atomausstieg hat die Strompreise in Deutschland stark steigen lassen.",
     "umstrittene Kausalaussage — differenziert, eher irreführend"),
    ("schwer", "C", "Die Kriminalität in Deutschland ist auf einem Allzeit-Rekordhoch.",
     "Cherry-Picking/kontextabhängig — je nach Delikt/Bezugsjahr"),
    ("schwer", "B", "Erneuerbare Energien deckten 2024 mehr als sechzig Prozent des deutschen Stromverbrauchs.",
     "präzise Zahl prüfen — Bruttostromverbrauch vs. -erzeugung"),
    ("schwer", "A", "Deutschland gibt mehr für Bürgergeld aus als für Verteidigung.",
     "Haushaltsvergleich, hängt an Abgrenzung — eher falsch"),

    ("leicht", "A", "Der gesetzliche Mindestlohn in Deutschland liegt bei 12,82 Euro pro Stunde.",
     "glatte Zahlenprüfung — Stand 2025; 2026er Erhöhung beachten"),
    ("leicht", "B", "Deutschland hat rund 84 Millionen Einwohner.",
     "unstrittig, amtliche Zahl — sollte ohne Eskalation gehen"),
    ("leicht", "C", "Der Bundestag hat aktuell mehr als 700 Abgeordnete.",
     "nach der Wahlrechtsreform 630 — klar widerlegbar"),
    ("leicht", "A", "Die Mehrwertsteuer in Deutschland beträgt regulär 19 Prozent.",
     "unstrittig — Kontrollfall, darf keine Tiefensuche auslösen"),
    ("leicht", "B", "Berlin ist die einwohnerstärkste Stadt Deutschlands.",
     "unstrittig — Kontrollfall"),
]


async def main():
    fc = FactChecker()
    print(f"===== QUALITÄT: {LABEL} =====")
    print(f"FactChecker: {fc.model_name} | Critique: {fc.critique_model_name}")
    print(f"Claims: {len(CLAIMS)} | Durchläufe: {RUNS}\n")

    # Suchtiefen getrennt nach Schwierigkeit — die eigentliche Kennzahl.
    by_level: dict[str, dict[str, int]] = {"schwer": {}, "leicht": {}}

    for run in range(1, RUNS + 1):
        if RUNS > 1:
            print(f"----- Durchlauf {run}/{RUNS} -----")

        for i, (level, sp, claim, expect) in enumerate(CLAIMS, 1):
            before = dict(search_mod.SEARCH_DEPTH_COUNTS)
            r = await fc.check_claim_async(sp, claim, context=CTX, episode_date=DATE)
            after = search_mod.SEARCH_DEPTH_COUNTS
            used = {k: after.get(k, 0) - before.get(k, 0) for k in ("fast", "advanced", "basic")}
            used = {k: v for k, v in used.items() if v}
            for k, v in used.items():
                by_level[level][k] = by_level[level].get(k, 0) + v

            srcs = r.get("sources", []) or []
            verdict = r.get("consistency", "?")
            dbl = r.get("double_check", False)
            evidence = (r.get("evidence") or "").replace("\n", " ")
            print(f"[{i}] ({level}) {claim}")
            print(f"    erwartet : {expect}")
            print(f"    VERDIKT  : {verdict}   | Quellen: {len(srcs)} | Suchen: {used} | double_check: {dbl}")
            if r.get("critique_note"):
                print(f"    Kritik   : {r['critique_note'][:160]}")
            print(f"    Begründung: {evidence[:280]}")
            for s in srcs[:4]:
                url = s.get("url", "") if isinstance(s, dict) else str(s)
                print(f"      · {url}")
            print()

    print(f"Suchtiefen gesamt: {dict(search_mod.SEARCH_DEPTH_COUNTS)}")
    for level in ("schwer", "leicht"):
        counts = by_level[level]
        total = sum(counts.values())
        if not total:
            continue
        share = counts.get("advanced", 0) / total
        print(f"  {level:7s}: {counts}  → advanced {share:.0%} von {total} Suchen")

    # Faustregel aus der Vorabmessung: Bleibt 'advanced' insgesamt unter etwa einem
    # Drittel, trägt die Ersparnis. Darüber ist 'agent' nur eine teurere Vorgabe.
    all_counts = search_mod.SEARCH_DEPTH_COUNTS
    grand = sum(all_counts.values())
    if grand:
        share = all_counts.get("advanced", 0) / grand
        print(f"\nadvanced-Anteil gesamt: {share:.0%}  "
              f"({'trägt' if share < 0.34 else 'zu hoch — Ersparnis fraglich'})")


if __name__ == "__main__":
    asyncio.run(main())
