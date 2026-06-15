# Live-Audio-Limits (Phase 3b) — Design

**Datum:** 2026-06-12
**Branch:** `worktree-session-multitenancy` (nicht gemergt)
**Status:** Design approved, bereit für Implementierungsplan

## Problem

Seit dem VPS-Cutover ist der Backend-Audio-Pfad öffentlich erreichbar und nur durch
den minimalen Zugangs-Gate (Phase 3a) geschützt. Ein gültiger Code kann heute
**unbegrenzt** Live-Audio aufnehmen: jede Session transkribiert beliebig lange
(AssemblyAI pro Minute) und extrahiert/prüft Claims pro Block. Es fehlt jede
app-seitige Kostenbremse.

### Schutzziel (vom Nutzer bestätigt)

1. **Missbrauch durch fremde Codes** — Codes gehen an Freunde/Bekannte; ein Code soll
   nicht stundenlang Audio durchjagen und die Rechnung sprengen (auch via curl/Skript,
   nicht nur über das eigene Frontend).
2. **Versehentliche Endlos-Session** — vergessenes Stoppen / hängende Aufnahme soll
   nicht ewig weiterlaufen.

Kein Euro-Deckel pro Sendung; es geht um Missbrauchsschutz + Sicherheitsnetz.

## Entscheidungen

- **Metrik: echte Audio-Sekunden** (nicht Claim-Checks, nicht Block-Anzahl).
  - Audio-Zeit ist der „Master-Hebel": Transkription läuft kontinuierlich; Extraktion +
    Checks (max 3/60s-Block) skalieren mit den Minuten. Wer Minuten deckelt, deckelt alles
    Nachgelagerte. Ein reines Claim-Check-Limit würde die „vergessene Session" (Audio ohne
    prüfbare Claims) **nicht** stoppen.
  - Echte Sekunden statt Block-Anzahl, weil „1 POST = 1 Block" durch einen böswilligen
    Client umgehbar ist (ein einziger Riesen-Block zählt als 1, kostet aber Stunden).
    AssemblyAI liefert `transcript.audio_duration` ohnehin gratis zurück.
- **Reichweite: kumulativ pro Code** (lifetime, über alle Sessions), exakt das
  Quick-Check-Muster (`quick_checks_used` / `quick_check_limit`).
- **Default-Limit: 5 Minuten lifetime pro Code** (env-konfigurierbar). Bewusst eng, da
  vorerst nur Freunde/Bekannte Codes bekommen.
- **`unlimited`-Codes** (Owner, `name:code:unlimited`) sind auch beim Audio unbegrenzt.

## Datenmodell & Konfiguration

Neue Spalten auf `codes` (analog Quick-Check):

```sql
-- frische Tabelle:
audio_seconds_used  INTEGER NOT NULL DEFAULT 0
audio_seconds_limit INTEGER            -- nullable; NULL = unbegrenzt (add_code setzt den Wert)

-- Migration bestehender Tabellen (backfillt vorhandene Codes fail-closed):
ALTER TABLE codes ADD COLUMN audio_seconds_used  INTEGER NOT NULL DEFAULT 0
ALTER TABLE codes ADD COLUMN audio_seconds_limit INTEGER DEFAULT 300  -- 5 Min, NICHT NULL
```

- Migrationen idempotent wie die vorhandenen Quick-Check-Migrationen.
- **Wichtig (fail-closed):** Der Migration-`DEFAULT 300` backfillt bestehende Codes auf
  5 Min — **nicht** `NULL`/unbegrenzt. Sonst wäre jeder Alt-Code nach Deploy unlimitiert.
- **Limit-Wert beim Seeding:** globaler Default aus env `LIVE_AUDIO_LIMIT_MINUTES`
  (Default `5`). Beim `seed_codes_from_env`/`add_code` wird `audio_seconds_limit` auf
  `LIVE_AUDIO_LIMIT_MINUTES * 60` gesetzt — außer der Code ist `unlimited`
  (dann `NULL`). Heuristik: ist `quick_check_limit` `None` (= `unlimited`-Owner), wird
  auch `audio_seconds_limit` `None`.
- Die `ACCESS_CODES`-Syntax (`name:code:limit`) bleibt **unverändert** — kein 4. Feld.
  Per-Code-Override = DB editieren (Runbook in `docs/deployment.md`, wie beim Quick-Check).

## Durchsetzung

Im bereits `require_code`-gated `POST /api/audio-block`. `require_code` liefert das
Code-Dict inkl. der neuen Spalten.

1. **Pre-Call-Guard A — Budget:** `audio_seconds_limit is not None and
   audio_seconds_used >= audio_seconds_limit` → `429` „Audio-Kontingent aufgebraucht",
   **kein** bezahlter Transkriptions-Call.
2. **Pre-Call-Guard B — Block-Größe:** `len(audio_data) > MAX_AUDIO_BLOCK_BYTES`
   (Default ~25 MB, env-überschreibbar) → `413`. Bounded den „eine-Riesen-Block"-
   Überschuss, *bevor* wir zahlen. Unser Recorder schickt nur ~60s-Blöcke.
3. **Transkribieren.** `TranscriptionService.transcribe()` gibt künftig
   `(formatted: str, audio_duration: float)` zurück (heute nur den String —
   `transcript.audio_duration` wird verworfen). Aufrufer in `audio.py` angepasst.
4. **Nach dem Call:** `db.increment_audio_seconds(code, int(round(audio_duration)))`.
   Folge: maximal *ein* Block überschießt das Budget, danach ist der Code dicht
   (gleiche „check-before, increment-after"-Semantik wie Quick-Check).

### Response

`POST /api/audio-block` liefert zusätzlich `remaining_seconds`
(`None` wenn unbegrenzt, sonst `max(limit - used, 0)`), damit das Frontend den
Rest anzeigen kann.

## Frontend-Verhalten

- `submitAudioBlock` in `api.js` fängt `429` ab → **Recorder stoppen** + klare Meldung
  („Audio-Kontingent für diesen Code aufgebraucht").
- **„noch X:XX übrig"-Anzeige im Header** (Teil des MVP, weil 5 Min schnell erreicht
  sind — sonst wirkt der Abbruch grundlos): aus `remaining_seconds` der letzten
  Block-Response. Beim Erreichen 0 → Stop + Meldung.

## Scope

**In Scope:** nur der Audio-Pfad (`/api/audio-block`).

**Bewusst out-of-scope:**
- Text-Pfad (`/api/text-block`, n8n) — verursacht keine Audio-Minuten, eigener gated Flow.
- Quick-Check — hat sein eigenes Kontingent.
- Reset-/Admin-Mechanismus — lifetime, deletion-proof (wie Quick-Check); Reset = DB editieren.
- Per-Session-Cap zusätzlich zum Code-Cap — nicht nötig, Code-Cap deckt beide Szenarien.

## Tests (TDD)

- `parse_access_codes` / `seed_codes_from_env`: neuer Default-Limit aus env korrekt gesetzt;
  `unlimited` → `audio_seconds_limit NULL`.
- `add_code` / `increment_audio_seconds`: Default, Inkrement, Persistenz.
- `POST /api/audio-block`: `429` bei `used >= limit` (kein Transkriptions-Call);
  Durchlass darunter; `unlimited`-Code umgeht Limit; `remaining_seconds` korrekt.
- Byte-Guard: Block > `MAX_AUDIO_BLOCK_BYTES` → `413`, kein Call.
- Überschuss-dann-Sperre: ein Block über Budget durchlassen, der nächste `429`.
- `transcribe()` neue Signatur `(str, float)` — Aufrufer/Mocks angepasst.

## Deployment-Hinweise

- env `LIVE_AUDIO_LIMIT_MINUTES` (Default 5) in `/opt/fact_check/.env` setzbar.
- Bestehende Codes auf dem VPS werden per Migration auf 5 Min (300s) backfillt
  (fail-closed). **Owner-Code-Wrinkle (wie beim Quick-Check):** ein bereits geseedeter
  `unlimited`-Owner-Code wird durch `INSERT OR IGNORE` **nicht** auf `NULL` aktualisiert
  und sitzt dann auf 5 Min fest → für unbegrenzt manuell
  `sqlite3 … "UPDATE codes SET audio_seconds_limit=NULL WHERE code='…'"` (Runbook in
  `docs/deployment.md`, analog zur bestehenden Quick-Check-Notiz).
- Ändert nichts an den Provider-Budget-Caps im Dashboard (bleiben die harte externe Grenze).
