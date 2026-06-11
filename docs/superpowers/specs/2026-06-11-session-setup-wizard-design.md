# Spec — Session-Setup-Wizard + Conversation Generalization

**Datum:** 2026-06-11
**Phase:** 2 (Teil B — Frontend/Onboarding). Teil A (Browser-Audio-Capture) ist ein
eigener, späterer Spec.
**Branch:** `worktree-session-multitenancy`
**Status:** Design abgestimmt (Brainstorming), bereit für Plan.

---

## Kontext & Motivation

Mit Multi-Tenancy (Phase 1) erzeugt jeder Nutzer seine eigene Session. Die Metadaten,
die ein Live-Check braucht (wer spricht, worüber), standen früher hartcodiert in
`config.py` (`Episode`: `show`/`date`/`guests`/`context`) und sind heute ein flaches,
show-zentriertes Formular auf `/new` (`NewSessionPage.jsx`).

Zwei Probleme:

1. **Die App ist nicht mehr auf TV-Shows beschränkt.** Sie soll auch **Interviews** und
   **private Gespräche** (z. B. mit Verwandten) abdecken. Das aktuelle Datenmodell und
   die Prompts gehen aber implizit von einer **politischen Talkshow mit benannten,
   parteigebundenen Gästen** aus.
2. **Das flache Formular** ist für Laien unübersichtlich und fragt Felder ab, die je nach
   Gesprächsart unterschiedlich (oder gar nicht) relevant sind (Partei bei einem privaten
   Gespräch, „Sendedatum" generell).

Dieser Spec ersetzt das Formular durch einen **geführten Wizard** und **generalisiert die
Gesprächs-Domäne** von „TV-Show" auf „beliebiges Gespräch" — über eine neutrale
Prompt-Fassung plus ein `conversation_type`-Signal, das das Modell adaptiv macht.

**Festgelegte Rahmenentscheidung (Brainstorming):** Wizard zuerst, Browser-Audio später.

---

## Scope

### In Scope
- Neuer Wizard auf `/new` (ersetzt das flache Formular in `NewSessionPage.jsx`).
- Neues `conversation_type`-Feld (`debate` | `interview` | `private`) auf Session-Payload + DB.
- **Generalisierung der zwei show-spezifischen Prompts** (`claim_extraction.md`,
  `speaker_labels.md`) auf gesprächsneutrale Formulierung — **ein** Prompt-Set, kein
  Per-Typ-Branching.
- **Generalisierung der Feld-Beschreibungen** in `claim_extraction.py`
  (`Sendung`→`Gespräch`, `Sendedatum`→entfällt).
- **Entfernung des „Sendedatum"** aus der Claim-Extraction-Pipeline (siehe Datum-Handling).

### Out of Scope (bewusst, je eigener Spec/Phase)
- **Browser-Audio-Capture** (`MediaRecorder` → `/api/audio-block`) — Phase 2 Teil A.
- **Strukturierte `participants[]`-Persistenz** in der DB — der Wizard formatiert
  client-seitig in die bestehende flache `guests[]`-Liste.
- **Per-Typ-Prompt-Varianten** — verworfen zugunsten eines generalisierten Sets.
- **Reference-Links im Wizard** — show-nah/nischig; das Deep-Link-Fallback-Formular
  behält sie, der Wizard fragt sie nicht ab.
- **Entfernen der `date`-Spalte aus DB/`Episode`** — Legacy-Episoden brauchen sie weiter
  für die Anzeige (Homepage/Titel). Nur der Extraction-Pfad wird vom Datum befreit.

---

## Datenmodell

Bewusst **minimal, keine strukturierte Migration**. Die flache `guests: list[str]` bleibt
(es ist alles, was das LLM konsumiert), wird aber semantisch von „Gäste/Sendung" auf
„Teilnehmer/Gespräch" umgedeutet. **Ein** neues Feld:

- **`conversation_type: str`** mit Werten `"debate" | "interview" | "private"`.
  - Auf `CreateSessionRequest` und `SessionResponse` (Default `"debate"`).
  - Neue Spalte auf der `sessions`-Tabelle via **idempotentem `ALTER TABLE`**
    (`conversation_type TEXT DEFAULT 'debate'`); bestehende/Legacy-Zeilen defaulten auf
    `"debate"`.
  - Auf `Episode` (`from_session_row` liest die Spalte, Default `"debate"`;
    `episode_to_session_dict`/`config.py`-Mapping reicht sie durch).
  - **Abgrenzung zum bestehenden `type`-Feld:** `type` (`show`/`youtube`) ist ein
    Legacy-/Audioquellen-Feld und bleibt unangetastet. `conversation_type` ist die
    Gesprächsart. Die beiden Achsen werden nicht vermischt.

- **`context` wird optional** (ist es im Model bereits, `default=""`). Überspringt der
  Nutzer den Themen-Schritt, defaultet `context` auf ein typ-abgeleitetes Label, damit das
  Modell immer minimalen Kontext hat:
  - `debate` → `"Öffentliche Debatte"`
  - `interview` → `"Interview"`
  - `private` → `"Privates Gespräch"`

- **`guests[]`** wird vom Wizard pro Gesprächsart formatiert (Details unter Wizard-UX).

### Wizard → Session-Payload Mapping

| Wizard-Eingabe | Session-Feld |
|---|---|
| Gesprächsart | `conversation_type` |
| Personen (pro Typ formatiert) | `guests: list[str]` |
| Thema (optional, sonst Typ-Default) | `context` |
| (auto, aus Typ + erster Person) | `title` |
| — (nicht erhoben) | `date=""`, `reference_links=[]`, `type="show"` |

---

## Datum-Handling

Da künftig **jede neue Session ein Live-Check** ist, ist ein vom Nutzer geliefertes
„Sendedatum" bedeutungslos. Relevant bleibt einzig das **tatsächliche aktuelle Datum** für
die zeitliche Verankerung des Fact-Checkers.

- **Entfernen aus der Extraction-Pipeline:**
  - `ClaimExtractionInput.date` (Feld `"Sendedatum, z. B. 'Oktober 2025'"`) wird gelöscht.
  - Die `date=`-Parameter auf `extract_claims_async` / `extract_async` / `extract`
    (`claim_extraction.py`) werden entfernt.
  - Das `ep_date`-Threading in `routers/audio.py` (`ep_date = ep.date`,
    `date=ep_date` im `extract_claims_async`-Call) entfällt.
  - → Das Extraction-Modell erhält **kein** Datum mehr.
- **Bleibt unverändert:** `fact_checker.py` füllt `{current_date}` aus
  `datetime.now().strftime("%B %Y")` pro Run — das reale Jetzt, unabhängig von der Session.
- **Wizard fragt kein Datum** und sendet keins (`date=""`).
- **Legacy-`date`-Spalte bleibt** auf `Episode`/`sessions` für die **Anzeige** vergangener
  veröffentlichter Episoden (`config.py` `Episode.info`/`"Sendung vom {date}"`,
  `HomePage.jsx`-Legacy-Liste). Nur der Extraction-Pfad wird datumsfrei; die Anzeige bleibt.

---

## Conversation Generalization (Prompts + Feld-Semantik)

`conversation_type` wird dem LLM als Kontext mitgegeben, damit **ein** neutrales
Prompt-Set sich selbst an die Gesprächsart anpasst.

- **`prompts/claim_extraction.md`:**
  Rolle `"Professionelle Inhaltsanalystin für deutsche Talkshow-Transkripte."`
  → gesprächsneutral, z. B. `"Professionelle:r Analyst:in für deutschsprachige
  Gesprächs-/Transkriptanalyse."` Extraktionslogik (Dekontextualisierung, Zerlegung)
  unverändert.
- **`prompts/speaker_labels.md`:**
  Partei ist nicht mehr das Framing. Ableitung der Zuordnung aus „(1) Gesprächsverlauf,
  (2) verfügbare Teilnehmer-Infos (Rolle, Zugehörigkeit **falls vorhanden**)". Bei
  privaten Gesprächen ohne Partei greift weiterhin der Gesprächsverlauf.
- **`backend/services/claim_extraction.py` Feld-Beschreibungen:**
  - `SpeakerLabelsInput.guests`: `"Teilnehmer der Sendung, z. B. [...]"`
    → `"Teilnehmer des Gesprächs, z. B. [...]"`.
  - `ClaimExtractionInput.guests`: `"Teilnehmer der Sendung"` → `"Teilnehmer des Gesprächs"`.
  - `ClaimExtractionInput.context`: `"Thematischer Hintergrund der Sendung"`
    → `"Thematischer Hintergrund des Gesprächs"`.
  - `ClaimExtractionInput.date`: **gelöscht** (s. Datum-Handling).
  - **Neu:** `conversation_type` als Feld auf `ClaimExtractionInput` **und**
    `SpeakerLabelsInput`, damit das Modell die Gesprächsart sieht (z. B. enge Beschreibung:
    `"Art des Gesprächs: debate | interview | private"`). Das Threading
    (`routers/audio.py` → `resolve_labels_async` / `extract_claims_async`) wird um
    `conversation_type` ergänzt.
- **`prompts/fact_checker.md`:** **unverändert** (bereits gesprächsneutral — eine
  Tatsachenbehauptung wird unabhängig vom Gesprächsort gleich geprüft).
- **Englische Prompts (`prompts/en/`):** außerhalb des Scopes (nicht aktiv genutzt).

**Public-API-Verträglichkeit:** Die Signatur-Änderungen an `ClaimExtractor`
(`date=` raus, `conversation_type=` rein) sind koordiniert mit dem einzigen Aufrufer
(`routers/audio.py`) und den Tests. Der `extract`/`extract_async`-Backcompat-Wrapper wird
entsprechend angepasst.

---

## Wizard-UX (`/new`)

Ersetzt das flache Formular. **Eine Route**, interne Schritt-Zustandsmaschine (kein
Route-pro-Schritt), Fortschrittsanzeige, animierte Übergänge, Zurück/Weiter über State.
Eine Frage pro Schritt.

### Flow

1. **Gesprächsart** — drei Kacheln:
   🏛️ **Öffentliche Debatte / Talkshow** · 🎙️ **Interview** · 💬 **Privates Gespräch**.
   Auswahl setzt `conversation_type` und verzweigt Schritt 2.

2. **Personen** — verzweigt nach Auswahl:
   - **Öffentliche Debatte:** dynamische Personen-Liste, pro Person **Name** + **Partei/
     Organisation** + **Rolle/Funktion** („weitere Person hinzufügen").
     Format → `"Heidi Reichinnek (Linke, Fraktionsvorsitzende)"`.
   - **Interview:** interviewte Person (**Name** + **Partei/Org** + **Rolle**) ·
     interviewende Person/Medium (**nur Name**, optional).
     Format → `"Robert Habeck (Grüne, Minister)"`, `"Caren Miosga (Moderatorin)"`.
   - **Privates Gespräch:** Teilnehmende nur als **Vorname/Rolle**, **keine Partei** —
     bewusst schlank; Personenliste **optional** (darf leer bleiben).
     Format → `"Onkel Klaus"`.
   - Leere/teilweise Felder werden beim Formatieren weggelassen (kein
     `"Name (, )"`-Artefakt).

3. **Thema (optional)** — Freitext „Worum geht es?", **überspringbar** (v. a. beim privaten
   Gespräch). Übersprungen → `context` = Typ-Default (s. Datenmodell).

4. **Übersicht & Start** — Zusammenfassung aller Angaben + **editierbarer Auto-Titel**
   (Default aus Typ-Label + erster benannter Person, z. B. `"Interview: Robert Habeck"`;
   ohne benannte Person nur das Typ-Label). „Session erstellen" → `createSession(payload)`
   → `navigate("/" + session_id)`.

### Zugangscode
Wie bei `/pruefen`: der app-weite Code aus `localStorage` (`fc_access_code`, gesetzt durch
den Homepage-Unlock) wird automatisch als `X-Access-Code` mitgesendet. Ein Code-Feld
erscheint nur als **Deep-Link-Fallback**, wenn kein Code gespeichert ist (`needsCode`).
401/403 → Code verwerfen + Hinweis (bestehende Logik aus `NewSessionPage.jsx` übernommen).

### Komponentenstruktur
- `NewSessionPage.jsx` wird zur Wizard-Hülle (Schritt-State via `useReducer`, Fortschritt,
  Navigation, Submit). Schritt-Inhalte als kleine, fokussierte Unterkomponenten
  (`StepConversationType`, `StepParticipants`, `StepTopic`, `StepReview`).
- Die **reine Logik** (Schritt-Übergänge, Per-Typ-Personen-Formatierung, Typ-Default-
  Context, Titel-Ableitung) liegt in testbaren Hilfsfunktionen (z. B.
  `wizardReducer` + `buildSessionPayload(state)`), unabhängig vom DOM.

---

## Fehlerbehandlung

- **Validierung:** Gesprächsart ist Pflicht (Schritt 1). Personen sind bei `debate`/
  `interview` empfohlen, aber leere Liste blockiert nicht hart (das Modell arbeitet
  best-effort über generische Sprecher-Labels); bei `private` explizit optional. Thema
  optional. Titel darf nicht leer sein (Auto-Default greift).
- **Backend-Fehler:** `createSession` 401/403 → Code-Feld zurücksetzen + Meldung;
  sonstige Fehler → Fehlermeldung im Review-Schritt, „erneut versuchen" ohne Datenverlust.
- **Migration:** `ALTER TABLE ... ADD COLUMN conversation_type` ist idempotent
  (try/except oder `PRAGMA`-Check, analog zu den Quick-Check-Quota-Spalten).

---

## Testing

### Backend
- `conversation_type` wird akzeptiert, persistiert und in `SessionResponse` zurückgegeben;
  Default `"debate"` bei fehlendem Feld und bei Legacy-Zeilen.
- Idempotente Migration: zweimaliges Anwenden bricht nicht; bestehende `sessions`-Rows
  bekommen den Default.
- `Episode.from_session_row` liest `conversation_type` (Default `"debate"`).
- Extraction-Pipeline ohne `date`: `extract_claims_async` läuft ohne `date`-Param;
  `ClaimExtractionInput` hat kein `date`-Feld mehr; bestehende `TestModel`/`FunctionModel`-
  Tests grün nach Signatur-Anpassung.
- `conversation_type` erreicht `ClaimExtractionInput`/`SpeakerLabelsInput` (über
  angepasstes Threading in `audio.py`).
- `fact_checker` `current_date` unverändert (Regressions-Sanity).

### Frontend
- `wizardReducer`: Schritt-Vor/Zurück, Verzweigung nach Typ, Personen hinzufügen/entfernen.
- `buildSessionPayload`: korrekte Per-Typ-Formatierung der `guests[]` (inkl. Weglassen
  leerer Teilfelder), Typ-Default-`context` bei übersprungenem Thema, Titel-Ableitung,
  `date=""`/`reference_links=[]`.
- Frontend-Build grün.

---

## Verifikationskriterien (Definition of Done)

- Wizard auf `/new` ersetzt das flache Formular; alle drei Gesprächsarten erzeugen eine
  Session mit korrekt formatierten `guests[]` + `conversation_type` + (Default-)`context`.
- Kein „Sendedatum" mehr im Extraction-Pfad; Fact-Checker nutzt weiter das reale Datum.
- Prompts + Feld-Beschreibungen gesprächsneutral; `conversation_type` erreicht das Modell.
- Legacy-Episoden (z. B. Maischberger) funktionieren unverändert (Anzeige inkl. Datum,
  Default `conversation_type="debate"`).
- Alle Backend-Unit-Tests grün, `ruff` clean, Frontend-Build ok.

---

## Abhängigkeiten

- Phase 1 (Session-Scoping, `owner_code`, Sessions-Router) — erfüllt.
- Phase 3a (Zugangs-Gate, `localStorage`-Code) — erfüllt.
- Unabhängig von Phase 2 Teil A (Browser-Audio); der Wizard funktioniert auch, solange
  Audio noch über `listener.py` kommt.
