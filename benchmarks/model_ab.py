"""
Self-contained A/B-Benchmark für die Fact-Check-Pipeline.

Misst pro Modell: (A) LLM-Vorstufen-Timing, (B) parallele Check-Stufe
(Timing + Qualität), (C) Token-Verbrauch → Kosten.

Der Harness patcht `build_model` zur LAUFZEIT so, dass Modellnamen mit '@'
(z. B. `gemini-3.8-flash@eu`) über Requesty (OpenAI-kompatibel) laufen, alle
anderen direkt über Google. Damit lassen sich Requesty-Modelle als Primärmodell
testen, OHNE `backend/services/llm_base.py` zu ändern — die Produktion bleibt
unberührt.

AUSFÜHREN (auf dem VPS, wo die API-Keys liegen):

    # Baseline (aktuelle Live-Config aus .env):
    ssh hostinger "cd /opt/fact_check && AB_LABEL='baseline' \\
      PYTHONPATH=/opt/fact_check /root/.local/bin/uv run python benchmarks/model_ab.py"

    # Kandidat, alle Stufen auf Requesty-EU-Flash:
    ssh hostinger "cd /opt/fact_check && AB_LABEL='3.8-flash@eu' \\
      GEMINI_MODEL_CLAIM_EXTRACTION='gemini-3.8-flash@eu' \\
      GEMINI_MODEL_FACT_CHECKER='gemini-3.8-flash@eu' \\
      PYTHONPATH=/opt/fact_check /root/.local/bin/uv run python benchmarks/model_ab.py"

Stellschrauben per Env:
    AB_LABEL                       Anzeigename des Laufs
    GEMINI_MODEL_CLAIM_EXTRACTION  steuert Resolve + Extract (beide!)
    GEMINI_MODEL_FACT_CHECKER      steuert die Check-Stufe
    GEMINI_MODEL_SELF_CRITIQUE     steuert die Self-Critique
    FC_ENV                         Pfad zur .env (Default: /opt/fact_check/.env)
    RATE_IN / RATE_OUT             $/1M Token, überschreibt die RATES-Tabelle
                                   (nötig für Modelle, die unten nicht gelistet sind)

STOLPERFALLEN (aus Erfahrung):
  * `uv` ist im nicht-interaktiven SSH nicht im PATH → voller Pfad
    /root/.local/bin/uv (via `ssh hostinger "command -v uv"` verifizieren).
  * PYTHONPATH=/opt/fact_check ist nötig (Imports `from config import ...`).
  * load_dotenv sucht relativ zum SKRIPT, nicht zum CWD → daher expliziter Pfad.
  * Das Ergebnis-Dict nutzt englische Keys: `consistency`, `sources`, `evidence`
    (der deutsche Key `quellen` entsteht erst beim DB-Mapping).
  * Läufe streuen stark (Check-Stufe ±20–30 s je nach API-Last) → für belastbare
    Aussagen 2–3 Läufe mitteln, nicht aus einem Lauf schließen.
  * Überschreiben von Produktionscode/-config blockt der Auto-Mode-Klassifizierer;
    dieser Harness ändert bewusst NICHTS an der App.
"""
import asyncio
import os
import time

from dotenv import load_dotenv

load_dotenv(os.getenv("FC_ENV", "/opt/fact_check/.env"))

# --- Laufzeit-Patch: '@'-Namen über Requesty routen -------------------------
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider


def _google_provider():
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY/GOOGLE_API_KEY nicht gesetzt")
    return GoogleProvider(api_key=key)


def _requesty_provider():
    key = os.getenv("REQUESTY_API_KEY")
    if not key:
        raise ValueError("REQUESTY_API_KEY nicht gesetzt (für '@'-Modelle nötig)")
    base = os.getenv("REQUESTY_BASE_URL", "https://router.requesty.ai/v1")
    return OpenAIProvider(base_url=base, api_key=key)


def _layer(name: str):
    if "@" in name:
        return OpenAIModel(name, provider=_requesty_provider())
    return GoogleModel(name, provider=_google_provider())


def _patched_build_model(primary: str, fallback: str | None = None):
    models = [_layer(primary)]
    if fallback:
        models.append(_layer(fallback))
    if os.getenv("PROVIDER_FALLBACK_ENABLED", "true").lower() != "false" and os.getenv("REQUESTY_API_KEY"):
        models.append(OpenAIModel(
            os.getenv("PROVIDER_FALLBACK_MODEL", "claude-opus-4-8@eu"),
            provider=_requesty_provider(),
        ))
    return models[0] if len(models) == 1 else FallbackModel(*models)


# Beide Module binden build_model als lokalen Namen → beide patchen.
import backend.services.fact_checker as _fc_mod
import backend.services.claim_extraction as _ex_mod
_fc_mod.build_model = _patched_build_model
_ex_mod.build_model = _patched_build_model
# ---------------------------------------------------------------------------

from backend.services.claim_extraction import ClaimExtractor
from backend.services.fact_checker import FactChecker
from backend.utils import to_dict
from pydantic_ai.usage import UsageLimits

LABEL = os.getenv("AB_LABEL", "?")

TRANSCRIPT = """Sprecher A: Wir müssen ehrlich sein: Die Inflation in Deutschland lag 2023 im Jahresdurchschnitt bei rund sechs Prozent, das war die höchste seit Jahrzehnten.
Sprecher B: Das stimmt, aber gleichzeitig ist der Anteil erneuerbarer Energien am Strommix 2023 erstmals über fünfzig Prozent gestiegen.
Sprecher A: Der Mindestlohn liegt seit Januar 2025 bei zwölf Euro zweiundachtzig, und trotzdem reicht das vielen Familien nicht.
Sprecher C: Deutschland hat 2023 mehr als eine Million Flüchtlinge aufgenommen, das belastet die Kommunen enorm.
Sprecher A: Die Arbeitslosenquote lag zuletzt bei etwa sechs Prozent, und die Wirtschaft ist 2023 leicht geschrumpft."""
GUESTS = ["Anna Weber", "Thomas Klein", "Julia Berger"]
CONTEXT = "Politik-Talkshow, Bundespolitik Deutschland, Wirtschaft und Energie"

CLAIMS6 = [
    {"name": "Anna Weber",   "claim": "Die Inflationsrate in Deutschland lag 2023 im Jahresdurchschnitt bei rund sechs Prozent."},
    {"name": "Thomas Klein", "claim": "Der Anteil erneuerbarer Energien am Strommix in Deutschland lag 2023 erstmals über fünfzig Prozent."},
    {"name": "Anna Weber",   "claim": "Der gesetzliche Mindestlohn in Deutschland liegt seit Januar 2025 bei 12,82 Euro pro Stunde."},
    {"name": "Julia Berger", "claim": "Deutschland hat 2023 mehr als eine Million Flüchtlinge aufgenommen."},
    {"name": "Anna Weber",   "claim": "Die Arbeitslosenquote in Deutschland lag zuletzt bei etwa sechs Prozent."},
    {"name": "Anna Weber",   "claim": "Die deutsche Wirtschaft ist 2023 leicht geschrumpft."},
]

# Rate cards $/1M Token. Bei fehlendem Eintrag RATE_IN/RATE_OUT per Env setzen.
RATES = {
    "gemini-3.8-flash@eu": {"in": 0.825, "out": 4.13},
    "gemini-2.5-pro":      {"in": 1.25,  "out": 10.0},
    "gemini-2.5-flash":    {"in": 0.30,  "out": 2.50},
}


def _rate(model: str) -> dict:
    if os.getenv("RATE_IN") and os.getenv("RATE_OUT"):
        return {"in": float(os.getenv("RATE_IN")), "out": float(os.getenv("RATE_OUT"))}
    return RATES.get(model, {"in": 0.0, "out": 0.0})


def _toks(usage):
    i = getattr(usage, "input_tokens", None)
    if i is None:
        i = getattr(usage, "request_tokens", 0) or 0
    o = getattr(usage, "output_tokens", None)
    if o is None:
        o = getattr(usage, "response_tokens", 0) or 0
    return i, o


async def main():
    ex = ClaimExtractor()
    fc = FactChecker()
    print(f"===== A/B: {LABEL} =====")
    print(f"Extractor: {getattr(ex, 'model_name', '?')} | FactChecker: {fc.model_name} | "
          f"Critique: {fc.critique_model_name} | parallel={fc.parallel_enabled} workers={fc.max_workers}\n")

    # (A) Vorstufen
    t = time.perf_counter(); resolved = await ex.resolve_labels_async(TRANSCRIPT, GUESTS, conversation_type="debate"); t_res = time.perf_counter() - t
    t = time.perf_counter(); claims = await ex.extract_claims_async(resolved, GUESTS, context=CONTEXT, conversation_type="debate", excluded_speakers=[]); t_ext = time.perf_counter() - t
    cd = [to_dict(c) for c in claims]
    t = time.perf_counter(); selected = await ex.select_async(cd); t_sel = time.perf_counter() - t
    print(f"[A] Vorstufen  Resolve {t_res:.1f}s | Extract {t_ext:.1f}s ({len(claims)} Claims) | "
          f"Select {t_sel:.1f}s ({len(selected)}) | Summe {t_res + t_ext + t_sel:.1f}s")

    # (B) Check-Stufe: 6 Claims parallel
    t = time.perf_counter(); results = await fc.check_claims_async(CLAIMS6, context="Bundespolitik Deutschland", episode_date="September 2026"); t_chk = time.perf_counter() - t
    print(f"[B] 6 Checks parallel: {t_chk:.1f}s ({t_chk / 6:.1f}s/Claim eff.)")
    for r in results:
        print(f"      [{str(r.get('speaker', '?')):13}] {str(r.get('consistency', '?')):8} | "
              f"Quellen {len(r.get('sources', []) or [])} | {str(r.get('original_claim', ''))[:45]}")

    # (C) Token-Verbrauch → Kosten (1 repräsentativer Check, direkt)
    uc = fc._build_user_message("Anna Weber", CLAIMS6[0]["claim"], context="Bundespolitik Deutschland", episode_date="September 2026")
    rc = await fc.agent.run(uc, usage_limits=UsageLimits(request_limit=fc.request_limit))
    ci, co = _toks(rc.usage())
    rate = _rate(fc.model_name)
    cost = (ci * rate["in"] + co * rate["out"]) / 1_000_000
    print(f"\n[C] 1 Check: in={ci} out={co} tok -> ${cost:.4f}  (Rate in ${rate['in']}/M out ${rate['out']}/M)")
    print(f"    Hochrechnung 6 Checks/Block: ~${cost * 6:.3f}"
          + ("" if rate["in"] else "   [!] keine Rate hinterlegt – RATE_IN/RATE_OUT setzen"))


if __name__ == "__main__":
    asyncio.run(main())
