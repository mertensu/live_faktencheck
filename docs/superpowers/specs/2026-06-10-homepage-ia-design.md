# Spec — Phase 1b: Homepage / Informationsarchitektur

**Datum:** 2026-06-10
**Branch:** `worktree-session-multitenancy`
**Roadmap:** `docs/superpowers/ROADMAP-session-app.md` (Phase 1b)
**Status:** Design abgenommen, bereit für Implementierungs-Plan.

## Problem

Mit Phase 1 sind Sessions privat und nur per Link abrufbar — die Startseite hat ihren
ursprünglichen „Schaufenster"-Zweck (Live-Faktenchecks präsentieren) verloren. Heute
zeigt `HomePage.jsx` zwei divergierende Varianten (Production: nur veröffentlichte
Episoden als Liste; Dev: TV/YouTube-Gruppen) plus einen nachträglich angeflanschten
`/pruefen`-CTA. Es gibt keinen klaren Einstieg in die zwei nutzbaren Modi (Quick Check,
Live-Session), und beide sind zugangscode-gegatet, ohne dass die Startseite das
abbildet.

## Ziel

Eine **balancierte Landing-Page** (eine Spalte, mobile-first), die beide Zielgruppen
bedient:
- **Nutzer mit Code** (Operatoren): schneller Einstieg in Quick Check oder Live-Session.
- **Öffentlichkeit ohne Code**: Produkt verstehen + Beispiele als Vertrauensbeleg sehen.

Konkret: Pitch → ein Zugangscode-Unlock → zwei gleichwertige Aktions-Karten → Beispiel-
Sektion (Legacy-Episoden). Layout-Richtung **A (linearer Scroll, eine Spalte)** wurde
gewählt (gegen Gate-first-App-Shell und Zwei-Spalten-Hero).

## Nicht-Ziele (out of scope)

- Offenes Registrierungssystem / Login jenseits des bestehenden Zugangscodes.
- Admin-UI für Codes (weiterhin via DB/SQL).
- Eigene Archiv-Seite (`/archiv`) — Beispiele bleiben als Sektion auf der Startseite.
- TV/YouTube-Gruppierung der Beispiele (vereinfacht zu flacher Liste).
- Überarbeitung von `/pruefen`, `/new`, `/about`, `/trusted-domains` selbst (nur ihre
  Verlinkung von der Startseite ändert sich).
- WebSocket / Background-Verarbeitung.

## Festgelegte Entscheidungen (aus Brainstorming)

1. **Homepage-Job:** balancierte Landing — Pitch + zwei Einstiege + Beispiele auf einer Seite.
2. **Entry-Modi:** zwei gleichwertige Karten — Quick Check (`/pruefen`) und Live-Session
   (`/new`); Live trägt einen kleinen „beta"-Hinweis (erst mit Phase 2 voll nutzbar).
3. **Legacy-Episoden:** als „Beispiele"-Sektion auf der Startseite (nicht ausgelagert).
4. **Zugangscode:** **Single Unlock auf der Startseite** — ein Code-Feld schaltet beide
   Karten frei; nach Unlock gehen die Karten direkt in den Flow (Code via `localStorage`
   geteilt, kein erneutes Fragen).
5. **Flow-Seiten behalten ihr eigenes Code-Feld** als Fallback für Deep-Links.

## Lösung

### Frontend — `HomePage.jsx` (Neufassung)

Eine einzige Seite (kein `isProduction`-Branch mehr), vier gestapelte Blöcke:

1. **Hero** — `<h1>Live-Faktencheck</h1>` + ein Satz Pitch. Kein Scroll-Indicator.
2. **Unlock** — neue kleine Komponente (`AccessUnlock` o.ä.):
   - Code-Input (`type=password`, `autoComplete=off`) + Button „Freischalten".
   - Bei Submit: ruft `validateCode(code)` (neuer api.js-Helper) → `GET /api/validate-code`.
     - Erfolg: `setAccessCode(code)`, Seitenzustand → unlocked, optionale Begrüßung
       „Eingeloggt als {name}".
     - 401/403: Fehlermeldung („Ungültiger Zugangscode"), Feld leeren.
   - **Beim Laden:** wenn `getAccessCode()` bereits einen Code liefert, rendert die Seite
     sofort unlocked (kein erneutes Eintippen). Optional: stillschweigende Re-Validierung
     im Hintergrund (nice-to-have, nicht erforderlich).
3. **Zwei Aktions-Karten** (responsive Grid/Flex, Stack auf schmalen Screens):
   - 🔎 **Behauptung prüfen** → `/pruefen`. „Ein Zitat oder eine Aussage einfügen und
     sofort einen Faktencheck erhalten."
   - 🎙 **Live-Session starten** → `/new`. „Eine Sendung live mitschneiden und Aussagen in
     Echtzeit prüfen." Kleiner „beta"-Tag.
   - **Locked-Zustand** (kein gültiger Code): Karten sichtbar, aber `aria-disabled`,
     reduzierte Opacity + Schloss-Glyph; Klick navigiert NICHT, sondern fokussiert das
     Code-Feld. **Unlocked:** normale `<Link>`s.
4. **Beispiele-Sektion** — Heading „Beispiele" + ein Satz; wiederverwendet die bestehende
   `show-item`-Liste + `getEpisodeDisplayName()`, gespeist aus `useShows()`. Links auf
   `/{session_id}`. Flache Liste (TV/YouTube-Gruppierung entfällt), `test`-Filter bleibt.

### Frontend — `api.js`

- Neuer Helper `validateCode(code)`: `GET /api/validate-code` mit `X-Access-Code`-Header
  (nutzt vorhandene `authHeaders()`/Code-Mechanik); gibt das Code-Objekt zurück oder wirft
  bei non-ok (mit `detail`-Message), analog zu `submitQuickCheck`.

### Frontend — `Navigation.jsx`

- Optionaler „Beispiele"-Link, der zur Beispiele-Sektion der Startseite ankert/scrollt.
  Logo + About bleiben. `/trusted-domains` bleibt aus dem Top-Nav (unverändert).

### Backend — neuer Endpoint

`GET /api/validate-code` in `routers/config.py` (neben `/api/health` — beides leichte,
nicht-bezahlte Status-Endpunkte):
- Abhängigkeit: bestehende `require_code` (kein Header → 401, ungültig/inaktiv → 403).
- Erfolg: 200 mit öffentlichen Feldern der Code-Row, z.B. `{name, quick_check_limit,
  quick_checks_used}` — **keine** sensiblen Felder, **kein** Roh-Code im Body.
- **Side-effect-free** (kein bezahlter externer Call, kein DB-Write) — der einzige Zweck
  ist, einen Code billig zu prüfen.

### Styling — `App.css`

- Neue Klassen für Hero, Unlock-Feld, Aktions-Karten (inkl. Locked-Zustand + beta-Tag),
  Beispiele-Sektion — im bestehenden visuellen Stil.
- Die in Phase Q bewusst offen gelassenen Klassen jetzt stylen: `quota-note`,
  `quick-check-result`, `quick-check-history`. `quick-check-cta` (alter Homepage-CTA)
  entfällt, da durch die Karten ersetzt.

## Datenfluss

```
Seitenladung
  └─ getAccessCode() vorhanden? ── ja ─→ Seite unlocked rendern
                                  └ nein ─→ Karten locked, Code-Feld sichtbar

Unlock-Submit
  └─ validateCode(code) → GET /api/validate-code (require_code)
        ├─ 200 → setAccessCode(code), unlocked, Karten aktiv
        └─ 401/403 → Fehler anzeigen, Feld leeren

Karte klicken (unlocked)
  └─ <Link> nach /pruefen bzw. /new → Flow nutzt vorhandenen Code aus localStorage
```

## Fehlerbehandlung

- Ungültiger/fehlender Code beim Unlock → klare deutsche Fehlermeldung, Feld leeren,
  Karten bleiben locked.
- `validateCode`-Netzwerkfehler → Fehlermeldung, kein Unlock.
- Direkter Deep-Link auf `/pruefen` oder `/new` ohne vorherigen Unlock → die Flow-Seiten
  haben weiterhin ihr eigenes Code-Feld (Fallback, unverändert).

## Test-Strategie

- **Backend:** Tests für `GET /api/validate-code` analog `test_access_gate.py`:
  - gültiger Code → 200 + erwartete Felder (kein Roh-Code, keine sensiblen Felder).
  - fehlender Header → 401.
  - ungültiger/inaktiver Code → 403.
  - bestätigen: kein DB-Write / kein externer Call (side-effect-free).
- **Frontend:** kein Test-Harness vorhanden → Verifikation via `bun run build` + manueller
  Klick-Test (Unlock-Flow, Locked-Zustand, Karten-Navigation, Beispiele-Links, Mobile-
  Stack).
- Voller Unit-Suite-Lauf grün (`uv run pytest backend/tests -m "not integration"`) +
  `ruff check` clean.

## Betroffene Dateien

- `frontend/src/pages/HomePage.jsx` (Neufassung)
- `frontend/src/components/` — ggf. neue `AccessUnlock`-Komponente
- `frontend/src/services/api.js` (`validateCode`)
- `frontend/src/components/Navigation.jsx` (optionaler Beispiele-Link)
- `frontend/src/App.css` (neue + Phase-Q-Restklassen)
- `backend/routers/config.py` — `GET /api/validate-code`
- `backend/tests/test_access_gate.py` (oder neue Datei) — Endpoint-Tests
- `docs/superpowers/ROADMAP-session-app.md` — Phase 1b auf ✅ nach Abschluss

## Abhängigkeiten

- Phase 1 (Sessions, `useShows`), Phase 3a (`require_code`, codes-Tabelle), Phase Q
  (`/pruefen`) — alle erfüllt auf diesem Branch.
- Unabhängig von Phase 2 (Browser-Audio) — die Live-Karte verlinkt auf den bestehenden
  `/new`-Flow und trägt einen beta-Hinweis.
