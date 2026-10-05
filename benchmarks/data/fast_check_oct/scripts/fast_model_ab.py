"""
A/B for the fast checker: synthesis model and/or Tavily results per query.

Per claim: reformulate once (GEMINI_MODEL_REFORMULATE) → search → synthesis with A and B.
With equal MAX_RESULTS_A/B the search runs once and both models see identical evidence, so
only the model differs; otherwise each variant searches the same queries with its own
max_results. No fallback chain: a failing model shows up as an error instead of silently
becoming another model.

    CLAIMS=claims.json uv run python benchmarks/fast_model_ab.py

Env: MODEL_A (default: current GEMINI_MODEL_FAST_CHECK default), THINKING_A (default low),
     MODEL_B (default gemini-2.5-pro; empty = run A only; names with "@" run via Requesty), THINKING_B (default: model default),
     MAX_RESULTS_A / MAX_RESULTS_B (default TAVILY_MAX_RESULTS or 5), REPEAT (default 1), OUT,
     NO_PRESS_B=1 (B searches on its own without the "Qualitätsjournalismus" domains),
     REFORM_MODEL / REFORM_THINKING / REFORM_PROMPT (reformulator override; "@" names via Requesty),
     PROMPT_A / PROMPT_B (path to an alternative synthesis prompt),
     MINI_DEEP=1 (B = A's verdict, but when A says "unklar"/"keine Datenlage", model B writes
     follow-up queries for what A said is missing, searches them and re-synthesizes on all hits).
Claims may carry deep_consistency (reference from the deep checker); it is copied through.
"""

import os
import sys
import json
import time
import asyncio
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from pydantic import BaseModel, Field  # noqa: E402
from pydantic_ai import Agent  # noqa: E402
from pydantic_ai.models.google import GoogleModel  # noqa: E402
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings  # noqa: E402
from pydantic_ai.providers.openai import OpenAIProvider  # noqa: E402

import backend.services.search as search  # noqa: E402
from backend.services.claim_extraction import ClaimExtractor, ReformulatedClaim  # noqa: E402
from backend.services.fast_fact_checker import FastFactChecker, FastVerdict, Source, DEFAULT_MODEL  # noqa: E402
from backend.utils import load_prompt  # noqa: E402
from backend.services.llm_base import _provider, settings_with_thinking  # noqa: E402
from backend.services.trusted_domains import TRUSTED_DOMAINS, TRUSTED_DOMAINS_BY_CATEGORY, source_tier  # noqa: E402

CLAIMS = os.getenv("CLAIMS", "claims.json")
OUT = os.getenv("OUT", "fast_model_ab.jsonl")
MODEL_A = os.getenv("MODEL_A", DEFAULT_MODEL)
THINKING_A = os.getenv("THINKING_A", "low")
MODEL_B = os.getenv("MODEL_B", "gemini-2.5-pro").strip()
THINKING_B = os.getenv("THINKING_B", "")
_MAX_DEFAULT = os.getenv("TAVILY_MAX_RESULTS", "5")
MAX_RESULTS_A = os.getenv("MAX_RESULTS_A", _MAX_DEFAULT)
MAX_RESULTS_B = os.getenv("MAX_RESULTS_B", _MAX_DEFAULT)
REPEAT = int(os.getenv("REPEAT", "1"))
NO_PRESS_B = os.getenv("NO_PRESS_B", "") == "1"
MINI_DEEP = os.getenv("MINI_DEEP", "") == "1"
REFORM_MODEL = os.getenv("REFORM_MODEL", "")
REFORM_THINKING = os.getenv("REFORM_THINKING", "low")
REFORM_PROMPT = os.getenv("REFORM_PROMPT", "")
PROMPT_A = os.getenv("PROMPT_A", "")
PROMPT_B = os.getenv("PROMPT_B", "")
UNDECIDED = tuple(x.strip() for x in os.getenv("MINI_DEEP_ON", "unklar").split(","))
FOLLOW_DEPTH = os.getenv("FOLLOW_DEPTH", "advanced")

FOLLOW_UP_PROMPT = """Eine schnelle Faktenprüfung hat eine Behauptung aus einer Live-Sendung geprüft und kam
zu keinem klaren Urteil ('unklar'). Ihre Begründung sagt, was in den Suchergebnissen fehlt oder
nicht passt. Du planst EINE gezielte Nachrecherche wie ein erfahrener Faktenprüfer.

Schreibe 1–2 deutsche Suchanfragen (Stichworte, 3–8 Wörter), die genau die Lücke schließen:
- Fehlt eine Vergleichszahl, ein Durchschnitt, ein Rang oder eine Gesamtsumme: suche genau diese
  Größe mit dem Fachbegriff, unter dem sie in einer amtlichen Statistik oder Studie steht.
- Stützt sich die Begründung nur auf Presse, eine Partei oder einen Verband: suche die
  Originalquelle dahinter (Statistikamt, Ministerium, Forschungsinstitut, Studie).
- Fehlen Daten für den genannten Zeitpunkt: suche den nächstliegenden Stand (Quartal, Vorjahr).
- Hängt das Urteil an einer behaupteten Ursache oder Wirkung: suche Studien oder Daten, die
  diesen Zusammenhang untersuchen — auch solche, die ihm widersprechen.
Wiederhole nicht die bisherigen Suchanfragen."""


class ReformulatedDiverse(ReformulatedClaim):
    search_queries: list[str] = Field(
        default_factory=list,
        description="Genau 5 kurze deutsche Suchanfragen (Stichworte), je aus einem anderen "
                    "Blickwinkel: Kern, Datenquelle, Entwicklung, Maßstab, Einordnung.",
    )


UNIFIED_CONSISTENCY = """Empirische Konsistenz des Kerns der Behauptung. Wähle genau eine von vier Stufen:
- 'hoch': Die verfügbaren Daten stützen den Kern — auch wenn die Belege überwiegend stützend, aber nicht vollständig schlüssig sind. Abweichungen im Rahmen der Rundung und Nebenaspekte, zu denen die Treffer nichts sagen, senken die Stufe nicht.
- 'niedrig': Die verfügbaren Daten widersprechen dem Kern — auch wenn die Belege überwiegend widersprechen, aber nicht vollständig schlüssig sind.
- 'unklar': Widersprüchliche Studien oder Belege ohne klare Richtung; wirklich nicht bestimmbar. Ausnahme: Behauptet die Aussage ausdrücklich eine Ursache und die Daten belegen nur die Entwicklung, nicht die Ursache, ist das 'unklar', nicht 'hoch'.
- 'keine Datenlage': Keine relevanten Daten oder empirischen Belege zu diesem Thema gefunden."""


class FastVerdictUnified(FastVerdict):
    consistency: Literal["hoch", "niedrig", "unklar", "keine Datenlage"] = Field(description=UNIFIED_CONSISTENCY)


class LegacyVerdict(FastVerdict):
    """The live schema before the move (descriptions as on main)."""
    evidence: str = Field(description='Kurze deutschsprachige Einschätzung (ein, höchstens zwei Sätze) mit der entscheidenden Zahl und ihrer Quelle.')
    consistency: Literal["hoch", "niedrig", "unklar", "keine Datenlage"] = Field(description="Empirische Konsistenz der Behauptung. Wähle genau eine von vier Stufen:\n- 'hoch': Die verfügbaren Daten stützen die Behauptung — auch wenn die Belege überwiegend stützend, aber nicht vollständig schlüssig sind.\n- 'niedrig': Die verfügbaren Daten widersprechen der Behauptung — auch wenn die Belege überwiegend widersprechen, aber nicht vollständig schlüssig sind.\n- 'unklar': Widersprüchliche Studien oder Belege ohne klare Richtung; wirklich nicht bestimmbar.\n- 'keine Datenlage': Keine relevanten Daten oder empirischen Belege zu diesem Thema gefunden.")
    sources: list[Source] = Field(default_factory=list, description='Primärquellen mit URL und kurzem informativem Titel')


class FollowUp(BaseModel):
    queries: list[str]

_PRESS = set(TRUSTED_DOMAINS_BY_CATEGORY.get("Qualitätsjournalismus", []))
DOMAINS_NO_PRESS = [d for d in TRUSTED_DOMAINS if d not in _PRESS]


def _agent(checker: FastFactChecker, model: str, thinking: str, prompt: str | None = None,
           output_type=FastVerdict) -> Agent:
    """Gemini names go to Google directly; names with "@" (e.g. gpt-6-luna@eu) via Requesty,
    where the thinking level becomes the OpenAI reasoning effort."""
    if "@" in model:
        provider = OpenAIProvider(
            base_url=os.getenv("REQUESTY_BASE_URL", "https://router.requesty.ai/v1"),
            api_key=os.environ["REQUESTY_API_KEY"],
        )
        settings = OpenAIChatModelSettings(openai_reasoning_effort=thinking) if thinking else None
        llm = OpenAIChatModel(model, provider=provider)
    else:
        llm, settings = GoogleModel(model, provider=_provider()), settings_with_thinking(thinking)
    return Agent(
        llm, output_type=output_type, instructions=prompt or checker.prompt_template,
        model_settings=settings, retries=1,
    )


async def _synth(agent: Agent, msg: str, found: set[str]) -> dict:
    t0 = time.perf_counter()
    try:
        out = (await agent.run(msg)).output
    except Exception as e:
        return {"error": repr(e), "synth_s": round(time.perf_counter() - t0, 2)}
    return {
        "synth_s": round(time.perf_counter() - t0, 2),
        "consistency": out.consistency,
        "evidence": out.evidence,
        "sources": [s.url for s in out.sources if s.url in found],
    }


async def _search(checker: FastFactChecker, claim: str, queries: list[str], max_results: str,
                  no_press: bool = False):
    # tavily_search reads TAVILY_MAX_RESULTS per call; A and B search one after the other.
    os.environ["TAVILY_MAX_RESULTS"] = max_results
    search.TRUSTED_DOMAINS = DOMAINS_NO_PRESS if no_press else TRUSTED_DOMAINS
    t0 = time.perf_counter()
    results = await checker._gather_evidence(claim, queries)
    return results, round(time.perf_counter() - t0, 2)


async def _mini_deep(checker, fu: Agent, synth: Agent, c: dict, queries: list[str],
                     first: dict, res: list[dict]) -> dict:
    """Second round for an undecided first verdict: targeted queries → search → re-synthesize."""
    t0 = time.perf_counter()
    msg = (f"Behauptung: {c['claim']}\nSendedatum: {c.get('episode_date') or '—'}\n"
           f"Bisherige Suchanfragen: {'; '.join(queries)}\n"
           f"Urteil: {first['consistency']}\nBegründung: {first['evidence']}")
    try:
        follow = list((await fu.run(msg)).output.queries)[:2]
    except Exception as e:
        return {**first, "mini_deep": True, "error": repr(e)}
    seen = {x.get("url") for x in res}
    # An empty claim keeps _build_queries from searching the bare claim a second time.
    depth, checker.search_depth = checker.search_depth, FOLLOW_DEPTH
    t_s = time.perf_counter()
    try:
        hits = await checker._gather_evidence("" if len(follow) >= 2 else c["claim"], follow)
    finally:
        checker.search_depth = depth
    follow_search_s = round(time.perf_counter() - t_s, 2)
    extra = [x for x in hits if x.get("url") not in seen]
    merged = res + extra
    out = await _synth(synth, _message(checker, c, merged), {x.get("url") for x in merged})
    out.update(mini_deep=True, first=first["consistency"], follow_queries=follow,
               extra_hits=len(extra), follow_search_s=follow_search_s,
               mini_deep_s=round(time.perf_counter() - t0, 2))
    return out


def _message(checker: FastFactChecker, c: dict, results: list[dict]) -> str:
    return (
        f"Kontext der Sendung: {c.get('context') or '—'}\n"
        f"Sendedatum: {c.get('episode_date') or '—'}\n"
        f"Sprecher: {c.get('speaker') or '—'}\n"
        f"Behauptung: {c['claim']}\n\n"
        f"Suchergebnisse aus vertrauenswürdigen Quellen:\n{checker._format_evidence(results)}"
    )


async def main() -> None:
    claims = json.loads(Path(CLAIMS).read_text())
    checker = FastFactChecker()
    a = _agent(checker, MODEL_A, THINKING_A, Path(PROMPT_A).read_text() if PROMPT_A else None,
               LegacyVerdict if os.getenv("FIELD_A") == "legacy" else FastVerdict)
    b = (_agent(checker, MODEL_B, THINKING_B, Path(PROMPT_B).read_text() if PROMPT_B else None,
                FastVerdictUnified if os.getenv("FIELD_B") == "unified" else FastVerdict)
         if MODEL_B else None)
    fu = _agent(checker, MODEL_B, THINKING_B, FOLLOW_UP_PROMPT, FollowUp) if MINI_DEEP and b else None
    extractor = ClaimExtractor()
    if REFORM_MODEL:
        prompt = Path(REFORM_PROMPT).read_text() if REFORM_PROMPT else None
        extractor.reformulator = _agent(
            checker, REFORM_MODEL, REFORM_THINKING, prompt or load_prompt("claim_reformulation.md"),
            ReformulatedDiverse if REFORM_PROMPT else ReformulatedClaim,
        )

    rows = []
    with open(OUT, "w") as f:
        for run in range(REPEAT):
            for c in claims:
                guests = c.get("guests") or []
                if isinstance(guests, str):
                    guests = json.loads(guests or "[]")
                t0 = time.perf_counter()
                r = await extractor.reformulate_claim_async(
                    c["claim"], speaker=c.get("speaker", ""), guests=guests, context=c.get("context", ""),
                )
                queries = list(getattr(r, "search_queries", []) or [])
                reform_s = round(time.perf_counter() - t0, 2)
                res_a, search_a = await _search(checker, c["claim"], queries, MAX_RESULTS_A)
                if (MAX_RESULTS_B == MAX_RESULTS_A and not NO_PRESS_B) or not b or MINI_DEEP:
                    res_b, search_b = res_a, search_a
                else:
                    res_b, search_b = await _search(checker, c["claim"], queries, MAX_RESULTS_B, NO_PRESS_B)
                ra = await _synth(a, _message(checker, c, res_a), {x.get("url") for x in res_a})
                if fu:
                    rb = (await _mini_deep(checker, fu, b, c, queries, ra, res_a)
                          if ra.get("consistency") in UNDECIDED else {**ra, "mini_deep": False})
                else:
                    rb = (await _synth(b, _message(checker, c, res_b), {x.get("url") for x in res_b})
                          if b else {"skipped": True, "synth_s": 0.0})
                ra.update(search_s=search_a, n_results=len(res_a))
                rb.update(search_s=search_b, n_results=len(res_b) + rb.get("extra_hits", 0))
                row = {
                    "run": run, "id": c.get("id"), "claim": c["claim"], "deep": c.get("deep_consistency", ""),
                    "prev_live": c.get("prev_live", ""),
                    "queries": queries, "reform_s": reform_s, "A": ra, "B": rb,
                }
                rows.append(row)
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                line = (f"r{run} #{row['id']:>3} deep={row['deep'] or '—':<15} "
                        f"A={ra.get('consistency', 'ERR'):<15} {ra['n_results']:>2} hits {ra['synth_s']:5.1f}s")
                if b:
                    line += f" | B={rb.get('consistency', 'ERR'):<15} {rb['n_results']:>2} hits {rb['synth_s']:5.1f}s"
                print(line)
                if rb.get("mini_deep"):
                    print(f"      Runde 2 ({rb.get('mini_deep_s', 0):.1f}s, +{rb.get('extra_hits', 0)} Treffer): "
                          f"{'; '.join(rb.get('follow_queries', []))}")

    def avg(xs):
        return sum(xs) / len(xs) if xs else float("nan")

    print(f"\nA={MODEL_A} (thinking {THINKING_A or 'default'}, max_results {MAX_RESULTS_A})  "
          f"B={MODEL_B} (thinking {THINKING_B or 'default'}, max_results {MAX_RESULTS_B}"
          f"{', no press' if NO_PRESS_B else ''})")
    print(f"reform {avg([r['reform_s'] for r in rows]):.2f}s")
    for v in ("A", "B") if b else ("A",):
        ok = [r[v] for r in rows if "error" not in r[v]]
        ts = sorted(x["synth_s"] for x in ok)
        print(f"{v}: synth avg {avg(ts):.2f}s  median {ts[len(ts) // 2] if ts else float('nan'):.2f}s  "
              f"max {max(ts) if ts else float('nan'):.2f}s  errors {len(rows) - len(ok)}  "
              f"search {avg([x['search_s'] for x in ok]):.2f}s  hits {avg([x['n_results'] for x in ok]):.1f}")
        cons = [x["consistency"] for x in ok]
        srcs = [u for x in ok for u in x["sources"]]
        press = [u for u in srcs if source_tier(u)[1] == "Presse"]
        print(f"   verdicts {', '.join(f'{k} {cons.count(k)}' for k in sorted(set(cons)))}  "
              f"sources {len(srcs)}, press {len(press)}, "
              f"checks citing press {sum(any(source_tier(u)[1] == 'Presse' for u in x['sources']) for x in ok)}/{len(ok)}")
        ref = [r for r in rows if r["deep"] and "error" not in r[v]]
        if ref:
            agree = sum(r[v]["consistency"] == r["deep"] for r in ref)
            print(f"   agrees with deep checker: {agree}/{len(ref)}")


if __name__ == "__main__":
    asyncio.run(main())
