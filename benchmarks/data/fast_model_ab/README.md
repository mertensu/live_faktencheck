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

## Neuer Prompt, Flash vs Luna (01.10.2026)

`flash_vs_luna_v3.jsonl`: `claims15b.json`, 2 Läufe, identische Treffer, beide Thinking/Reasoning
low, Prompt-Stand v0.3.0 (`<consistency>` mit „Kern“). Vergleich gegen `flash_vs_luna.jsonl`
(alter Prompt, gleiche Claims).

| Variante | Prompt | Synthese Ø | Urteile (hoch / niedrig / unklar) | Stabil | Tief-Check-Treffer | Presse (Quellen / Checks) |
|---|---|---|---|---|---|---|
| Flash low | alt | 2,6 s | 11 / 11 / 8 | 9/15 | 8/10 | 26 von 62 / 17/30 |
| | **neu** | 3,8 s | 15 / 13 / 2 | 10/15 | 10/10 | 23 von 59 / 15/30 |
| Luna low | alt | 2,7 s | 2 / 9 / 19 | 14/15 | 6/10 | 18 von 57 / 14/30 |
| | **neu** | 2,3 s | 5 / 11 / 14 | 13/15 | 9/10 | 21 von 55 / 16/30 |

Je Claim (Lauf 1 Lauf 2, h/n/u):

| # | Flash alt → neu | Luna alt → neu |
|---|---|---|
| 31 | nn → hn | un → uu |
| 32 | un → nn | uu → nn |
| 33 | hh → hh | uu → hu |
| 34 | nn → nn | nn → nn |
| 35 | hh → nh | uu → uu |
| 36 | uh → hh | uu → uu |
| 37 | un → uh | uu → uu |
| 38 | un → hn | nn → nn |
| 39 | hh → uh | uu → uu |
| 40 | uu → hh | uu → uu |
| 269 | nu → nn | uu → un |
| 307 | hh → hh | hh → hh |
| 318 | un → nn | nn → nn |
| 319 | nn → nn | nn → nn |
| 329 | hh → hh | uu → hh |

- **Luna** ist mit dem neuen Prompt weniger übervorsichtig (19 → 14 „unklar“), trifft den
  Tief-Check jetzt 9/10 statt 6/10 und bleibt am stabilsten. Das restliche „unklar“ sitzt fast
  nur auf #31 #35–#40, und dort meist begründet: Die Treffer belegen die behauptete Ursache
  bzw. den Vergleich nicht (#35 „wegen politischer Entscheidungen der teuerste“, #37 „im
  Gegensatz zu 12 anderen“, #39 „Habeck hat … dadurch gesenkt“).
- **Flash** ist entschiedener geworden (8 → 2 „unklar“), Tief-Check 10/10, aber kaum stabiler
  (10/15) — und genau auf diesen Kausal-/Vergleichs-Claims kippt es in einem der Läufe auf
  „hoch“ (#35 mit unverlinktem Verivox, #37, #39 Kausalität ohne Beleg). Die 10/10 kommen von
  den 5 Maischberger-Claims, die Staging-Claims #31–40 haben keine Referenz.
- Lesart: Der Prompt hat beide Modelle in die gewünschte Richtung bewegt. Luna ist jetzt der
  vorsichtigere, aber konsistentere Prüfer; Flash wirkt auf Kausal-Claims zu nachsichtig.

## Ohne Presse-Domains (01.10.2026)

`no_press.jsonl`: `claims15b.json`, 1 Lauf, Flash low in A und B, gleiche Suchanfragen; B
sucht getrennt ohne „Qualitätsjournalismus“ (faz, handelsblatt, sz, zeit, spiegel,
tagesschau). Skript-Option `NO_PRESS_B=1`.

| Variante | Treffer Ø | Urteile (h / n / u) | Tief-Check | Zitierte Quellen | davon Presse | Checks mit Presse |
|---|---|---|---|---|---|---|
| mit Presse | 18,8 | 9 / 6 / 0 | 5/5 | 27 | 7 | 5/15 |
| ohne Presse | 17,8 | 6 / 7 / 2 | 5/5 | 27 | 0 | 0/15 |

- Presse verschwindet vollständig, die Lücke füllen amtliche und Forschungsquellen
  (#34, #35, #307 vorher nur/teils Presse, jetzt Destatis/Forschung/Land). Kaum Verlust an
  Treffern (−1 pro Claim), gleich viele zitierte Quellen, Tief-Check unverändert 5/5.
- Abweichende Urteile: #36 (Industriestrompreis) hoch → unklar — mit Presse stützte sich der
  Check allein auf tagesschau/ZEIT (BDEW-Zahl), ohne findet er keinen Wert: echter
  Recall-Verlust. #39 hoch → unklar (Kausalität, s. o. — eher ein Gewinn). #37 hoch → niedrig
  (Destatis-Zahl statt bpb; Claim-Formulierung mehrdeutig).
- Nur 1 Lauf: Urteilswechsel auf #31–40 liegen im Bereich des Lauf-Rauschens (vgl. Flash
  stabil 10/15). Der Presse-Effekt selbst ist eindeutig.

## Luna low mit 8 Treffern (01.10.2026)

`luna_low_8.jsonl`: `claims15b.json`, 2 Läufe, nur Luna low, `MAX_RESULTS_A=8`. Frage: Sinkt
der „unklar“-Anteil, wenn mehr Treffer da sind (Recall-Fälle #37, #269, #36)?

| Variante | Treffer Ø | Synthese Ø | Urteile (h / n / u) | Stabil | Tief-Check |
|---|---|---|---|---|---|
| Luna low, 5 Treffer (`flash_vs_luna_v3`) | 18,7 | 2,3 s | 5 / 11 / 14 | 13/15 | 9/10 |
| Luna low, 8 Treffer | 30,6 | 2,2 s | 5 / 10 / 15 | 10/15 | 8/10 |

Nein: Trotz 60 % mehr Treffern bleibt „unklar“ gleich, die Stabilität sinkt eher (Wechsel bei
#33 #34 #40 #269 #329, im Rahmen des Lauf-Rauschens). #37 und #36 bleiben „unklar“, weil auch
unter 8 Treffern die Vergleichszahl bzw. ein Durchschnittswert fehlt. Mehr vom Gleichen hilft
der Schnellprüfung nicht; diese Fälle brauchen gezieltes Nachsuchen (tiefe Prüfung).

## Mini-tief: Nachsuchen bei „unklar“ (01.10.2026)

`luna_mini_deep.jsonl` auf `claims10_deep.json`: 10 alte Deep-Checks aus Prod (Snapshot
01.10.), 3 niedrig (#91 #98 #476), 3 hoch (#100 #102 #203), 4 unklar (#108 #142 #224 #266).
Luna low, 2 Läufe. B = A, aber bei „unklar“/„keine Datenlage“ schreibt Luna aus der eigenen
Begründung 2 Nachsuch-Anfragen (`MINI_DEEP=1`), die neuen Treffer kommen dazu, neues Urteil.

| Variante | Urteile (h / n / u) | Tief-Check | Zusatzzeit bei „unklar“ |
|---|---|---|---|
| Luna low | 4 / 3 / 13 | 7/20 | – |
| + Mini-tief | 4 / 4 / 12 | 8/20 | Ø ~6,7 s, +1–10 Treffer |

Nur 1 von 14 Nachsuchen ändert das Urteil (#476 → niedrig). Das Nachsuchen findet die
Angaben meist — Luna entscheidet trotzdem nicht (#100: 18 Cent gefunden, aber „Oktober statt
September“; #203: 6,3 Mrd. gefunden, aber „nicht ausdrücklich nur Bürgergeld“; #98: Eurostat
H1 2025, aber „nicht September“). Schluss: ein Entscheidungs-, kein Suchproblem — Luna wendet
die Regeln zu Zeit und Bezug zu streng an. Mini-tief lohnt in dieser Form nicht.

## Prompt-Variante „im Kern“ (01.10.2026)

`luna_kern.jsonl`: Luna low mit `fast_fact_checker_kern.md` (`PROMPT_A`): „Im Kern richtig
heißt 'hoch', im Kern falsch 'niedrig'; Einschränkungen (Stand wenige Monate daneben, enger/
weiter gefasste Größe, Rundung, Zuspitzung) ändern die Stufe nicht, sie gehören in die
Begründung“; „anderer Zeitraum“ nicht mehr Grund für „unklar“. 25 Claims (`claims10_deep` +
`claims15b`), 1 Lauf, neue Suche (Treffer nicht identisch mit den Vergleichsläufen).

| | „unklar“ pro Lauf | Tief-Check (15 Refs) |
|---|---|---|
| Luna low, heutiger Prompt (`flash_vs_luna_v3` + `luna_mini_deep` A) | ~13,5 / 25 | ~8 / 15 |
| Luna low, „im Kern“ | 10 / 25 | 6 / 15 |

Weniger „unklar“, aber an den falschen Stellen: Deep-„unklar“ #142 #224 und #31 (IW-Prognose)
werden „hoch“, #37 wird „niedrig“ (Claim missverstanden). Die Zielfälle #98 #100 #102 #203 #36
bleiben „unklar“ — Luna nimmt Zeitanker in der Claim-Formulierung („Im September 2025 …“,
vom alten Umformulierer eingefügt) als Kern, wertet nach dem Sendedatum veröffentlichte Zahlen
ab (#203) und akzeptiert 17 statt 18 ct nicht als Rundung (#36). Live-Prompt unverändert.

## Flash auf den 10 Deep-Claims (01.10.2026)

`flash_deep10.jsonl`: Flash low, heutiger Live-Prompt, `claims10_deep.json`, 1 Lauf.
Urteile 5 / 3 / 2 (h/n/u), Tief-Check 6/10 — aber inhaltlich besser als die Zahl:

- Die Luna-Problemfälle entscheidet Flash wie der Deep-Check: #98 niedrig, #100 hoch, #203 hoch
  (#91 niedrig). Die echten Deep-„unklar“ #142 und #224 bleiben „unklar“.
- #266 (989,8 Mrd. Steuereinnahmen 2025 laut Destatis) und #108 „hoch“ gegen Deep-„unklar“:
  hier wirkt Flash richtiger als die Referenz.
- #476 „hoch“ gegen Deep-„niedrig“: 75.500 Fertigstellungen 2021–2025 (Landesstatistik); Lunas
  55–60 Tsd. zählten erst ab 2022 — Grenzfall, eher Abgrenzung der Legislaturperiode.
- Echter Fehler: #102 „niedrig“ — der Claim („zwölf Mitgliedstaaten in der Welt“) ist schon
  verunglückt formuliert.
- Presse: 7/10 Checks zitieren Presse (#100 nur Handelsblatt).

Schluss: Flash bleibt live; Luna zurückgestellt. Rest-Baustellen sind Claim-Formulierung und
Presse-Anteil, nicht „unklar“.

## Flash 3.6 (Google direkt) vs 3.8 (Requesty, EU) (01.10.2026)

`flash36_vs_38.jsonl`: `claims10_deep.json`, 1 Lauf, identische Treffer, beide Thinking low;
B = `vertex/gemini-3.8-flash@eu` über Requesty (3.6 gibt es dort nicht mit `@eu`).

| Variante | Synthese Ø | Urteile (h/n/u) | Tief-Check | Presse-Checks |
|---|---|---|---|---|
| 3.6 direkt | 3,2 s | 5 / 4 / 1 | 6/10 | 5/10 |
| 3.8 Requesty EU | 3,8 s | 4 / 3 / 3 | 6/10 | 4/10 |

Unterschiede nur bei #98 (3.8 „unklar“ wegen „nicht September“ — Luna-artig) und #142 (3.8
„unklar“ wie der Deep-Check). 3.6 selbst wechselt gegenüber `flash_deep10` bei #142 und #476 —
die Unterschiede liegen im Lauf-Rauschen. Thinking low kommt über Requesty an (+0,5 s, nicht
+5 s). Kein Qualitätsgewinn durch 3.8; ein Wechsel zu Requesty wäre eine Datenschutz-, keine
Qualitätsentscheidung.

## Woher kommt das Rauschen? 3.8 zweimal auf denselben Treffern (01.10.2026)

`flash38_twice.jsonl`: `claims15b.json`, 1 Lauf, A und B = `vertex/gemini-3.8-flash@eu`,
Thinking low, identische Treffer. **15/15 gleiche Urteile.** Das Urteil selbst ist also stabil;
die Lauf-zu-Lauf-Wechsel kommen aus Umformulierung/Suchanfragen/Treffern. Zwei parallele
Urteile auf denselben Treffern bringen nichts — Hebel sind stabilere Suchanfragen.

Nebenbefunde: 3.8 entscheidet die Staging-Claims gut (#35 niedrig, #37 hoch, #39 unklar wegen
unbelegter Ursache; 1/15 „unklar“, Tief-Check 5/5). Aber 2 von 30 Aufrufen über Requesty
brauchten ~28 s statt ~4 s — Latenz-Ausreißer, live ein Risiko (Timeout + Fallback nötig).

## Umformulierung: Luna medium + diverse Suchanfragen (02.10.2026)

`reform_luna_diverse.jsonl`: `claims15b.json`, 2 Läufe. Umformulierer = `gpt-6-luna@eu`,
Reasoning medium, Prompt `claim_reformulation_diverse.md` (genau 5 Anfragen aus festen
Blickwinkeln: Kern, Datenquelle, Entwicklung, Maßstab, Einordnung). Urteil =
`vertex/gemini-3.8-flash@eu`, Thinking low, Live-Prompt.

| | Stabil (2 Läufe) | Urteile (h/n/u) | Tief-Check | Umformulierung Median / max | Gesamt Median / max |
|---|---|---|---|---|---|
| heute (Flash 3.6 umformuliert + urteilt, `flash_vs_luna_v3`) | 10/15 | 11 / 11 / 8 → v3: 15 / 13 / 2 | 10/10 | 2,3 s | 10,2 s / 15,9 s |
| Luna medium divers + 3.8 | **13/15** | 14 / 14 / 2 | 10/10 | 2,9 s / 5,4 s | 10,7 s / 13,3 s |

Die hoch↔niedrig-Wechsel (#31 #38) sind weg; übrig bleiben #35 und #39 (unklar ↔ hoch, beides
Ursachen-Claims). Presse weiter 16/30 Checks. Vorbehalt: Basis urteilte mit 3.6, nicht 3.8 —
Modell- und Prompt-Effekt der Umformulierung sind noch nicht getrennt.

## Offen

- Live-Modell: Luna (neuer Prompt) statt Flash? Spricht dafür: stabiler, 10× billiger,
  schneller, fängt Kausalfehler. Dagegen: weiterhin ~halb „unklar“ auf den Staging-Claims.
- Presse aus `TRUSTED_DOMAINS` nehmen: Kosten sind einzelne Recall-Lücken (#36, Zahlen, die
  nur über Presse auffindbar sind, vgl. Berliner Zahlen); ggf. als zweite Stufe „Presse nur,
  wenn ohne nichts gefunden“.
