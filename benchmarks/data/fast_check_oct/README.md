# Schnellprüfung: Zweitstufen, ReAct, Suche und PDFs (02.–05.10.2026)

Fortsetzung von `../fast_model_ab/README.md`. Aufbau jedes Laufs (Skript, Claims,
Varianten) steht in `MANIFEST.md`; die Skripte liegen unter `scripts/` und liefen wie gehabt
im Wegwerf-Container aus dem Staging-Image auf dem VPS (`.env.staging`). Je Lauf 5–12 Claims,
jeweils **ein** Lauf. Unterschiede von 1–2 Claims liegen im Lauf-Rauschen. `deep` ist das
Urteil des alten ReAct-Tiefchecks (Referenz, keine Wahrheit).

## Ergebnisse

| Lauf (Datei) | Frage | Ergebnis | Zeit | Tavily |
|---|---|---|---|---|
| `round2_unklar_out` | Nachsuche (2 Anfragen, `advanced`) nur bei „unklar“ | 1 von 6 geändert (#103 → hoch, schwach belegt) | +11–16 s | ~4/Fall |
| `unified_out`, `schema_out` | Stufen-Definition nur im Schema (→ PR #18) | Ursachen-Claims #35 #39: hoch → unklar (4/4, gleiche Treffer); sonst gleich oder unklar → keine Datenlage | ±0 | 0 |
| `react` | ReAct, Agent sucht (≤5) und urteilt selbst | löst #522 #102 #108, aber zu nachsichtig: #98 #142 #39 #103 „hoch“ | 13–71 s, Median ~45 s | ~4/Claim |
| `react_judge` | Agent sucht, separates Urteil (Live-Urteiler) | kein falsches „hoch“; #98 und #142 wie deep; echte Gewinne 3/9 | 19–33 s | ~4/Claim |
| `staged` | Schnellprüfung, bei „unklar“ Agent in 2 parallelen Runden + Urteil | 0/6 sauber gelöst; #108 Stufe „hoch“ widerspricht der Begründung; drei zweifelhafte sichere Urteile (#522 #98 #142) erreichen die Zweitstufe nie | +11–40 s | ~4/Fall |
| `primary` | Anfrage „Entwicklung“ → Primärquelle (Sprecher/Partei + Zahl in „…“), 12 Claims mit deep | 0/12 geändert; die Anfrage findet Politiker-Biografien | ±0 | 6/Claim (Test) |
| `extract` | Tavily Extract auf die PDF-Treffer (Abschnitte passend zur Behauptung), neu urteilen | 11/12 gleich; #203 keine Datenlage → hoch (= deep, Zahl stand in BT-Drs. 20/13346 außerhalb des Ausschnitts); alle 93 PDFs extrahierbar | +1–4 s (Median 3 s) | 1 je 5 URLs (~1,6/Claim) |
| `studie` | Umformulierer: „Entwicklung“ → Pflicht-Anfrage „Studie“ (PR #19), A auf gespeicherten Treffern, B frisch; beide mit Extract bei „unklar“ | 8/12 gleich; #497 kD → hoch (= deep, „Bauüberhang“ 48.394); #142 unklar → hoch (schlechter, Kennzahl-Rosinenpicken); #224, #511 strittig; Extract änderte diesmal kein Urteil (#203 nur → unklar) | ±0 | 5/Claim |
| `englisch` | Maßstab-Anfrage auf Englisch bei internationalen Vergleichen, 7 Vergleichs-Claims | B nie schlechter; #37 niedrig → hoch (richtig, Eurostat: 12 EU-Staaten mit Atomstrom); #98 niedrig direkt über Eurostat (= deep); #35 mit Eurostat 1. Hj. 2025 (DE höchster Haushaltspreis); 30/35 Treffer der englischen Anfrage von Eurostat/OECD | ±0 | 6/Claim (Test) |
| `lang` | Entscheidet der Umformulierer (PR #19) richtig, wann die Maßstab-Anfrage englisch ist? 10 internationale + 10 innerdeutsche Claims × 2, nur Umformulierung | innerdeutsch 20/20 deutsch (nie fälschlich englisch); international 18/20 englisch (#102, #276 je einmal deutsch = bisheriges Verhalten) | – | 0 |

## Schlüsse

- Das Urteil ist auf gleichen Treffern weitgehend stabil (Ausnahme #511 einmal niedrig/unklar).
  Rauschen und Fehlurteile kommen aus den **Treffern**, nicht aus Modell oder Definition.
- **Nicht** weiterverfolgt: Zweitstufen mit neuer Suche für „unklar“ (26 Nachsuchen → 2
  zweifelhafte Änderungen), ReAct mit Selbsturteil (zu nachsichtig), Agentensuche live (zu
  langsam), Modell-/Thinking-Wechsel, Primärquellen-Anfrage.
- **Behalten/umsetzen:** Stufen nur im Schema (PR #18); Extract auf bereits gefundene
  Studien/PDFs bei „unklar“/„keine Datenlage“ (liest tiefer statt neu zu suchen).
- Recall-Kosten ohne Presse (PR #16): #98 und #203 waren am 01.10. mit Spiegel bzw. tagesschau
  richtig, jetzt „keine Datenlage“ (#203 rettet Extract).
- **Deutsche Anfragen finden Eurostat nie** (Eurostat veröffentlicht englisch); eine englische
  Maßstab-Anfrage bei internationalen Vergleichen trifft sofort die passende Meldung → in PR #19.
- Pflicht-Anfrage „Studie“ (PR #19): kein messbarer Nettogewinn (+#497, −#142); Extract
  wirkte in 1 von 2 Läufen auf #203.
- Anfragen-Blickwinkel: „Studie“ stand nur in 6/12 Anfragesätzen; „Entwicklung“ lieferte am
  wenigsten eigene zitierte Quellen (1, gegenüber Kern 5, Datenquelle 3, Maßstab 3,
  Einordnung 2) → Kandidat zum Ersetzen durch eine Pflicht-Anfrage „Studie“.

Eine unabhängige Auswertung derselben Rohdaten durch einen frischen Agenten kam zu denselben
Kernaussagen und betonte zusätzlich: Die schwersten Fehler stecken in sicheren Urteilen
(„hoch“/„niedrig“ auf unpassenden oder veralteten Treffern), die eine Zweitstufe nur für
„unklar“ nie erreicht.
