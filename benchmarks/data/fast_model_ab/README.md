# Schnellprüfung: Modell- und Such-A/Bs (23.–24.09.2026)

Ergebnisse von `benchmarks/fast_model_ab.py` für den schnellen Faktencheck der Live-Lane.
Gelaufen in einem Wegwerf-Container aus dem Staging-Image auf dem VPS; die Dateien lagen
dort unter `/tmp/fast_model_ab/` und sind am 01.10.2026 hierher gesichert worden.

Jede Zeile einer `.jsonl` ist ein Claim-Durchlauf: Umformulierung → Suchanfragen →
Tavily → Synthese mit Variante A und (optional) B. Bei gleichem `max_results` sehen A und
B **dieselben Treffer**, es unterscheidet sich also nur das Modell. `deep` ist das Urteil
des alten tiefen Checkers, soweit vorhanden (Referenz, keine Wahrheit).

## Claim-Sets

| Datei | Claims | mit Tief-Check-Referenz |
|---|---|---|
| `claims.json` | 10 (Staging #31–40) | 0 |
| `claims15.json` | 15 (Staging #31–40 + #495 #497 #501 #504 #511) | 5 |
| `claims15b.json` | 15 (Staging #31–40 + Maischberger 26.03.2026 #269 #307 #318 #319 #329) | 5 |

`maxres.jsonl` lief auf `claims15.json`, die Luna-Läufe auf `claims15b.json` (bzw. dessen
ersten 12 Claims). Bei 2 Läufen zählt jeder Referenz-Claim doppelt, daher „von 10“.

## Läufe

| Datei | A | B | Claims × Läufe |
|---|---|---|---|
| `fast_model_ab.jsonl` | Gemini 3.6 Flash, Thinking low | Gemini 2.5 Pro | 10 × 1 |
| `fast_model_ab_medium.jsonl` | Flash, Thinking low | Flash, Thinking medium | 10 × 1 |
| `maxres.jsonl` | Flash low, 5 Treffer/Anfrage | Flash low, 8 Treffer/Anfrage | 15 × 2 |
| `luna.jsonl` | Flash low | GPT-6 Luna (`gpt-6-luna@eu`, Reasoning-Default) | 12 × 1 |
| `luna_only.jsonl` | Luna, Reasoning-Default | — | 12 × 1 |
| `luna_low.jsonl` | Luna, Reasoning low | — | 15 × 2 |
| `flash_vs_luna.jsonl` | Flash low | Luna low (identische Treffer) | 15 × 2 |
| `luna_v2.jsonl` | **wertlos**: Tavily-Limit erreicht, 26/30 ohne Treffer | | 15 × 2 |

## Ergebnisse

Synthese-Zeit = nur der Modell-Aufruf (ohne Suche). „Stabil“ = gleiches Urteil in beiden
Läufen. Tief-Check-Treffer nur auf den Claims mit Referenz.

| Lauf | Variante | Synthese Ø | Urteile (hoch / niedrig / unklar) | Stabil | Tief-Check-Treffer |
|---|---|---|---|---|---|
| Pro vs Flash | Flash low | 3,5 s | 3 / 4 / 3 | – | – |
| | 2.5 Pro | 19,9 s | 3 / 4 / 3 | – | – |
| Thinking | Flash low | 2,4 s | 6 / 2 / 2 | – | – |
| | Flash medium | 6,6 s | 6 / 2 / 2 | – | – |
| Treffer | Flash, 5 | 3,1 s | 13 / 6 / 11 | 9/15 | 2/10 |
| | Flash, 8 | 3,1 s | 13 / 9 / 8 | 12/15 | 2/10 |
| Flash vs Luna | Flash low | 2,6 s | 11 / 11 / 8 | 9/15 | 8/10 |
| | Luna low | 2,7 s | 2 / 9 / 19 | 14/15 | 6/10 |
| Luna allein | Luna low | 2,8 s | 3 / 10 / 17 | 12/15 | 7/10 |

## Schlüsse (Stand 24.09.)

- **2.5 Pro** urteilt kaum anders, braucht aber ~20 s → nicht live.
- **Thinking medium** bringt bei Flash dieselben Urteile wie low, dauert 3× so lang → live bleibt low.
- **8 statt 5 Treffer** pro Anfrage: gleiches Tempo, stabilere Urteile (12 vs 9 von 15).
  Vorschlag: eigene Einstellung `FAST_TAVILY_MAX_RESULTS` (noch nicht umgesetzt).
- **GPT-6 Luna**: gleich schnell, laut Requesty ~10× billiger, deutlich stabiler, erkennt
  Kausal-, Absolut- und Gegenstandsfehler besser (#35 #37 #38 #39 #318) — aber stark
  übervorsichtig (19/30 „unklar“, nur 2 „hoch“). Flash besser bei #32 #33 #269 #329.
- Das Urteils-Rauschen kommt vor allem aus wechselnden Suchanfragen der Umformulierung.

Live blieb **Gemini 3.6 Flash, Thinking low**. Danach wurde der Bewertungs-Abschnitt in
`prompts/fast_fact_checker.md` überarbeitet (erst den „Kern“ bestimmen; ausdrückliche
Ursache gehört dazu; „unklar“ keine sichere Ausweichstufe), um Lunas Übervorsicht
abzubauen. Dieser Prompt ist seit v0.3.0 live, **wurde aber nie gemessen** — weder mit
Luna noch mit Flash.

## Presse-Anteil der genannten Quellen

Nachträglich aus denselben Daten ausgezählt (01.10.), Label nach `source_tier()`:

| Lauf | Variante | Zitierte Quellen | davon Presse | Checks mit ≥1 Presse-Quelle |
|---|---|---|---|---|
| Flash vs Luna | Flash low | 62 | 26 | 17/30 |
| | Luna low | 57 | 18 | 14/30 |
| Treffer | Flash, 5 | 59 | 40 | 24/30 |
| | Flash, 8 | 57 | 27 | 17/30 |

Trotz der Prompt-Regel („[Presse] nur, wenn keine bessere Quelle sie trägt“) stützt sich
etwa jeder zweite Check auch auf Presse. Mehr Treffer pro Anfrage senken den Anteil, weil
öfter amtliche Seiten dabei sind.

## Offen: nächster Test

1. **Aktueller Prompt, Flash vs Luna** auf `claims15b.json`, identische Treffer, 2 Läufe
   (~150 Tavily-Suchen). Frage: Ist Luna mit dem neuen Prompt weniger übervorsichtig, und
   hat der Prompt Flash verändert? Vergleich gegen `flash_vs_luna.jsonl`.
2. **Ohne Presse-Domains**: Tavily-Suche ohne die Kategorie „Qualitätsjournalismus“
   (faz.net, handelsblatt.com, sueddeutsche.de, zeit.de, spiegel.de, tagesschau.de — alle
   sechs, auch tagesschau.de)
   gegen die heutige Liste, gleiches Modell, 1 Lauf (~150 Suchen, da beide Varianten
   getrennt suchen). Messen: Presse-Anteil, Anzahl Treffer, Anteil „unklar“ /
   „keine Datenlage“ (verlieren wir Recall?), Tief-Check-Treffer.
