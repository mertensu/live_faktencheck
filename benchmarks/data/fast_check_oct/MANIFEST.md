# Experimente zur Schnellprüfung (Live-Faktencheck) — Aufbau, ohne Schlussfolgerungen

Projekt: `/Users/ulfmertens/Documents/live_faktencheck` (Repo; aktueller Code = `origin/main`,
lesbar mit `git show origin/main:<pfad>`; der lokale Checkout steht auf Branch
`fact-check-benchmarks`). Pipeline-Doku: `docs/llm_pipeline.md` auf origin/main.

## Live-Ablauf heute (origin/main, seit 05.10.2026)
1. Claim-Gate (Jev) → Umformulierer `gpt-6-luna@eu` (Reasoning medium) schreibt die Behauptung
   und genau 5 Suchanfragen aus festen Blickwinkeln.
2. Schnellprüfung (`backend/services/fast_fact_checker.py`): 5 Tavily-Suchen `basic` parallel
   (je 5 Treffer, nur vertrauenswürdige Domains, ohne Presse seit PR #16), ein Urteilsaufruf
   `vertex/gemini-3.8-flash@eu` (Thinking low) mit Schema `FastVerdict`
   (evidence → consistency ∈ hoch/niedrig/unklar/keine Datenlage → sources).
   Seit PR #18 stehen die Stufen-Definitionen nur im Schema (`backend/lang.py`), der Prompt
   `prompts/fast_fact_checker.md` ist verschlankt.
3. Latenz Satz→Ergebnis: Schnellprüfung ~8–12 s (Umformulierung 1,5–5 s, Suche ~4 s, Urteil 2–4 s).
   Requesty-Aufrufe haben gelegentlich Ausreißer (~20–37 s).

## Randbedingungen des Betreibers (Ulf)
- Checks dürfen 5–10 s länger dauern, wenn die Qualität besser wird.
- Tavily-Credits sind knapp (geteiltes Budget Prod/Staging/Benchmarks).
- Nur „unklar“-Urteile sollen ggf. durch eine zweite Stufe.
- Referenz: der alte ReAct-Tiefcheck (Tag `v0.2.0`, `backend/services/fact_checker.py`,
  `prompts/fact_checker.md`, gemini-2.5-pro, bis 35 Modellaufrufe) galt als gut;
  `deep` in den Daten = dessen Urteil, wo vorhanden (Referenz, keine Wahrheit).

## Ältere Läufe (23.09.–02.10.2026)
Beschrieben inkl. Tabellen in
`/Users/ulfmertens/Documents/live_faktencheck/benchmarks/data/fast_model_ab/README.md`
(Rohdaten daneben, `*.jsonl`; Claim-Sets `claims*.json`). Themen: 2.5 Pro vs Flash, Thinking,
Trefferzahl 5 vs 8, Luna vs Flash, Prompt-Versionen, ohne Presse, Mini-tief mit Luna,
Flash 3.6 vs 3.8, zweimal urteilen auf identischen Treffern, Umformulierer Luna divers.

## Läufe vom 02.10.–05.10.2026 (alle: VPS, Wegwerf-Container aus dem Staging-Image, je 1 Lauf)

Claim-Sets in `data/`: `claims_unklar.json` (8 Claims, die zuletzt „unklar“ waren: #102 #103
#107 #108 aus einer Staging-Session 02.10., #522 aus Prod 01.10., #98 #142 aus alten Deep-Checks,
#39 aus dem Staging-Set), `claims_unified.json` (+ #35 #37), `claims5.json` (#35 #39 #37 #98
#103), `claims_react.json` (9 = claims_unified ohne #37).

| Datei | Skript | Aufbau |
|---|---|---|
| `round2_unklar_out.jsonl` | `scripts/fast_model_ab.py` mit `MINI_DEEP=1` | A = Schnellprüfung (alter Prompt, vor PR #18). Bei A = „unklar“: Modell schreibt aus A's Begründung 1–2 Nachsuch-Anfragen, Tavily `advanced`, neues Urteil über alle Treffer (= B). 8 Claims. |
| `unified_out.jsonl` | `scripts/fast_model_ab.py`, `FIELD_B=unified`, `PROMPT_B=prompts/fast_fact_checker_unified.md` | Gleiche Treffer für A und B. A = Live-Prompt+Schema vor PR #18; B = Stufen nur im Schema (`UNIFIED_CONSISTENCY` im Skript), Prompt ohne Stufen. 10 Claims. |
| `schema_out.jsonl` | `scripts/fast_model_ab.py`, `FIELD_A=legacy`, `PROMPT_A=prompts/fast_fact_checker_live.md` | Gleiche Treffer. A = Stand vor PR #18, B = Stand PR #18 (heute live). 5 Claims. |
| `react.jsonl` | `scripts/react_bench.py` | ReAct: Flash 3.8 sucht selbst (Tool, 1 Anfrage/Aufruf, max 5 Suchen, 8 Modellaufrufe) und urteilt selbst (Schema PR #18). Keine Schnellprüfung vorab. 9 Claims. Treffer nicht gespeichert, nur Anfragen. |
| `react_judge.jsonl` | `scripts/react_judge_bench.py` | Agent sucht (wie oben, ohne eigenes Urteil, Hinweis bei 0 neuen Treffern), danach ein separates Urteil durch den Live-Urteiler über alle Treffer. Keine Schnellprüfung vorab. 9 Claims. Treffer gespeichert. |
| `staged.jsonl` | `scripts/staged_bench.py` | Phase 0 = komplette Live-Schnellprüfung (Umformulierer + 5 Suchen + Urteil). Nur bei unklar/keine Datenlage: Agent bekommt Treffertitel + erstes Urteil, sucht in ≤2 Runden à ≤3 parallele Anfragen, kein Urteil; danach separates Urteil über alle Treffer. 9 Claims. |

Hinweise zur Vergleichbarkeit: Jeder Lauf sucht neu (Treffer unterscheiden sich zwischen
Läufen, außer innerhalb eines A/B mit „gleichen Treffern“). Umformulierung läuft in den
`fast_model_ab`- und `staged`-Läufen jedes Mal neu. Zeiten in Sekunden, gemessen im Container.

## Nachträge 05.10.2026
| Datei | Skript | Aufbau |
|---|---|---|
| `primary.jsonl` | `scripts/primary_bench.py` | Ein Umformulierer-Lauf mit Zusatzfeld `primary_query`; A = Anfragen a–e, B = a,b,d,e + Primärquelle; alle 6 einmal gesucht, volle Treffer gespeichert. 12 Claims mit deep (`claims_primary.json`). |
| `extract.jsonl` | `scripts/extract_bench.py` | Gespeicherte A-Treffer aus `primary.jsonl`; B = dieselben + Tavily-Extract-Abschnitte für alle PDF-Treffer. |
| `studie.jsonl` | `scripts/studie_bench.py` | A = gespeicherte Live-Anfragen/Treffer, B = Umformulierer-Prompt aus PR #19 („Studie“), frisch gesucht; beide mit PR-#19-Prüfung (Extract bei unklar). |
| `englisch.jsonl` | `scripts/englisch_bench.py` | Ein Umformulierer-Lauf (PR #19) mit Zusatzfeld `yardstick_en`; A = a–e, B = a,b,c,yardstick_en,e. 7 Vergleichs-Claims (`claims_vergleich.json`). |
| `lang.jsonl` | `scripts/lang_decision_bench.py` | Nur Umformulierer (PR #19), 2 Läufe, 20 Claims (`claims_lang.json`, Feld `expect` en/de); keine Suche. |
| `grimm.jsonl`, `follow.jsonl`, `follow_grimm2.jsonl` | `scripts/single_claim.py`, `scripts/grimm_doc.py`, `scripts/follow_bench.py` | Grimm-Claim live (2 Läufe) vor/nach PR #20; follow.jsonl Teil 2 = 12 Deep-Claims auf gespeicherten Treffern aus `primary.jsonl`. Referenz: Untertitel des Höfgen-Videos (yt-dlp) + Finanzplan 21/601. |
| `press.jsonl` | `scripts/press_bench.py` | Gemeinsame Umformulierung, Grundsuche und Presse-Suche; A ohne, B mit Presse-Hinweisen (Code auf Branch `fast-check-press-hints`, nicht gemergt). 7 Claims (`claims_press.json`). |
