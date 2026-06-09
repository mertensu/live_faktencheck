# Phase 1 — Session-Multi-Tenancy (Design-Spec)

**Datum:** 2026-06-09
**Status:** Genehmigt (Brainstorming abgeschlossen)
**Scope:** Backend-Umbau von „eine globale Show" zu „viele parallele, isolierte Sessions".

---

## 1. Kontext & Ziel

Live Faktencheck ist heute ein Single-Operator-System: Eine einzige, hartkodierte
Episode (`config.py` → `EPISODES`) ist global aktiv (`state.current_episode_key`),
ein lokaler `listener.py` speist Audio ein, und ein Betreiber moderiert die Claims.

**Ziel von Phase 1:** Das Backend so umbauen, dass beliebig viele Sessions
**gleichzeitig und voneinander isoliert** laufen können. Jede Session ersetzt das
heutige Episode-Konzept und wird zur Laufzeit in der Datenbank erzeugt statt im Code
hartkodiert.

Diese Phase ist Teil eines größeren Vorhabens (App für alle Nutzer). Die weiteren
Phasen sind bewusst **nicht** Teil dieses Specs:

- **Phase 2:** Browser-Audio-Capture (Mikrofon Desktop/Handy) ersetzt `listener.py`.
- **Phase 3:** Zugangscodes (Gating der Session-Erstellung).
- **Phase 4:** VPS-Deployment (Backend dauerhaft auf Hostinger, Tunnel entfällt).
- **Separater Spec (Phase 1b):** Neugestaltung von Homepage / App-Informationsarchitektur.

### Nicht-Ziele (Phase 1)

- Keine Homepage-/UX-Neugestaltung — bestehende Startseite bleibt unverändert.
- Kein Browser-Audio — Test der Isolation erfolgt weiterhin über `listener.py`.
- Kein Zugangscode-Gating — Session-Erstellung ist in Phase 1 noch ungated.
- Keine WebSocket-/Push-Architektur — das bestehende Chunk-POST-+-Polling-Modell bleibt.

---

## 2. Kern-Ansatz

Das bestehende `Episode`-Konzept wird zur **dynamischen, in der DB gespeicherten
Session** verallgemeinert. Der globale `current_episode_key` entfällt; stattdessen
trägt jeder Request seine `session_id` mit. Dieser Ansatz wurde gewählt, weil er
**nahezu den gesamten bestehenden Pipeline-Code wiederverwendet** (Transkription,
Claim-Extraktion, Fact-Checker, DB-Schema) — die Tabellen `fact_checks` und
`pending_claims_blocks` hängen bereits an einem `episode_key`-String.

**Schlüssel-Idee für saubere Migration:** Für bestehende, veröffentlichte Episoden
gilt `session_id == alter episode_key`. Dadurch mappen alle vorhandenen Fact-Checks
1:1 auf die neuen Sessions, ohne Daten anzufassen.

Verworfene Alternativen:
- **WebSocket-„Rooms" mit Push** statt Polling — schönere Live-UX, aber großer Rewrite.
- **Job-basiert** (Aufnahme → Verarbeitung, kein Live-Gefühl) — verliert die Live-Eigenschaft.

---

## 3. Datenmodell

### Neue Tabelle `sessions`

```sql
CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,   -- uuid/slug für neue; == alter episode_key für Legacy
    title            TEXT NOT NULL DEFAULT '',  -- Show-/freier Titel
    date             TEXT NOT NULL DEFAULT '',
    guests           TEXT NOT NULL DEFAULT '[]', -- JSON: ["Name (Rolle)", ...], Moderator zuerst
    context          TEXT NOT NULL DEFAULT '',
    reference_links  TEXT NOT NULL DEFAULT '[]', -- JSON
    type             TEXT NOT NULL DEFAULT 'show',     -- show | youtube
    status           TEXT NOT NULL DEFAULT 'active',   -- active | ended
    visibility       TEXT NOT NULL DEFAULT 'private',  -- private | public (Legacy = public)
    owner_code       TEXT,               -- füllt Phase 3 (Zugangscode)
    created_at       TEXT NOT NULL,
    ended_at         TEXT
);
```

### `Episode`-Dataclass bleibt als View-Modell

Die `Episode`-Dataclass und ihre Properties (`speakers`, `episode_name`) bleiben
erhalten, werden aber künftig **aus einer `sessions`-Zeile** konstruiert statt aus dem
hartkodierten `EPISODES`-Dict. Eine Factory (`Episode.from_session_row(row)` o. ä.)
übernimmt das Mapping. So bleibt die nachgelagerte Pipeline-Logik unverändert.

### Scope-Schlüssel: Spalten-Umbenennung

In `fact_checks` und `pending_claims_blocks` wird die Spalte `episode_key` per
Migration auf `session_id` umbenannt (`ALTER TABLE … RENAME COLUMN`, ab SQLite 3.25
unterstützt, risikoarm). Eine konsistente Bezeichnung im gesamten Code. Da
Legacy-Sessions denselben String-Wert behalten, mappen alle bestehenden Fact-Checks
1:1 ohne Daten-Migration.

**Entscheidung:** Umbenennen (nicht: Spalte physisch `episode_key` lassen und nur im
API-Layer umbenennen) — die Doppelbenennung wäre eine dauerhafte Wartungsfalle.

---

## 4. Runtime-State & Nebenläufigkeit

Heutiger globaler State in `state.py` wird session-fähig:

| Heute (global) | Neu |
|----------------|-----|
| `current_episode_key: str \| None` | **entfällt** — jeder Request trägt `session_id` |
| `pipeline_events: dict` (keyed by `block_id`) | bleibt, jeder Eintrag bekommt Feld `session_id`; Status-Endpunkte filtern danach. `block_id` ist bereits global eindeutig. |
| `claim_queue: asyncio.Queue` (eine) | **eine gemeinsame Queue**; jedes Item trägt `session_id` |
| `queue_worker_task: Task` (einer) | **kleiner Worker-Pool** (`N`, Default 3, via Env `FACT_CHECK_WORKER_POOL_SIZE` konfigurierbar) |

**Worker-Pool-Begründung:** Eine gemeinsame Queue mit mehreren Workern erlaubt
parallele Abarbeitung mehrerer Sessions (kein Head-of-Line-Blocking bei einem langsamen
Fact-Check), deckelt aber die Gesamt-Parallelität — und damit die API-Kosten. Minimal
invasiv gegenüber dem heutigen Einzel-Worker (ein Item-Schema-Feld + Worker werden in
einem Pool gestartet).

---

## 5. API-Änderungen

Aus episode-zentrierten werden session-zentrierte Endpunkte.

| Heute | Neu | Zweck |
|-------|-----|-------|
| `EPISODES`-Dict + `/api/set-episode` | `POST /api/sessions` (anlegen → `session_id`), `GET /api/sessions/{id}`, `POST /api/sessions/{id}/end` | Session-CRUD ersetzt globales Episode-Setzen |
| `/api/audio-block` mit `episode_key` (Form, optional) | dito mit `session_id` (Pflicht) | Audio-Block → Session |
| `/api/pending-claims`, `/api/approve-claims`, `/api/text-block` | dito, alle mit `session_id` (Pflicht-Scope) | Claims pro Session isoliert |
| `/api/fact-checks?episode_key=…` | `…?session_id=…` | Ergebnisse pro Session |
| `/api/config/*` liest aus `EPISODES` | liest aus `sessions`-Tabelle | Konfig aus DB |

`POST /api/sessions` nimmt die Felder des heutigen Episode-Formulars entgegen (Titel,
Gäste mit Rolle, Kontext, optionale Referenz-Links) und erzeugt eine `sessions`-Zeile
mit generierter `session_id`, `status='active'`, `visibility='private'`.

`config.py`/`EPISODES` bleibt nur noch als **Seed-Quelle** (siehe §7) und kann
perspektivisch entfallen.

---

## 6. Frontend (Minimal-Scope)

Nur so viel, dass Sessions nutzbar sind — **keine** Homepage-Umgestaltung (eigener Spec):

- **Neues „Session anlegen"-Formular** (Titel, Gäste/Rollen, Kontext, Referenz-Links)
  → `POST /api/sessions` → erhält `session_id`, leitet auf die Live-Seite weiter.
- **`FactCheckPage` + `AdminView` auf `session_id` umstellen** statt globalem Episode-Key.
  Funktional identisch, nur pro Session gescoped.
- **Teilbarer Link** pro Session (z. B. `/session/{id}`) für die private Ansicht.
- Audio-Capture bleibt Phase 2: In Phase 1 sendet `listener.py` `session_id` statt
  `episode_key`.

---

## 7. Migration, Kompatibilität & Tests

### Migration

1. `sessions`-Tabelle anlegen (idempotent, `CREATE TABLE IF NOT EXISTS`).
2. `episode_key` → `session_id` in `fact_checks` und `pending_claims_blocks` umbenennen
   (idempotent: nur ausführen, wenn Spalte `episode_key` noch existiert).
3. Legacy-`EPISODES` **einmalig** als `sessions`-Zeilen einspielen: identische
   `session_id` (= alter Key), `visibility='public'`, `status='ended'`. Idempotent
   (`INSERT OR IGNORE`).

Ergebnis: Alle bestehenden Fact-Checks und veröffentlichten Episoden bleiben 1:1
erhalten und abrufbar.

### Tests (alle ohne API-Calls, `-m "not integration"`)

- **Session-CRUD:** anlegen, lesen, beenden.
- **Scope-Isolation:** Zwei parallele Sessions; Fact-Checks/Pending-Claims der einen
  Session sind in der anderen nicht sichtbar.
- **Worker-Pool:** Mehrere Sessions werden parallel abgearbeitet; Items behalten ihre
  `session_id`.
- **Migration:** Nach Migration ist eine Legacy-Episode als `public`/`ended` Session
  abrufbar und ihre bestehenden Fact-Checks bleiben über `session_id` auffindbar.
- **Pflicht-Scope:** Requests ohne `session_id` werden abgelehnt (kein stiller Fallback
  auf einen globalen Default mehr).

---

## 8. Offene Punkte für Folge-Phasen (nicht Teil von Phase 1)

- Homepage/IA-Neugestaltung — Startseite hat keinen „Schaufenster"-Zweck mehr, da neue
  Sessions privat/per-Link sind (Phase 1b, eigener Spec).
- Browser-Audio-Capture inkl. Tab-/System-Audio (Phase 2).
- Zugangscodes + `owner_code`-Befüllung + Rate-/Kosten-Limits (Phase 3).
- VPS-Deployment, systemd, TLS, Tunnel-Abbau (Phase 4).
- Auto-Expiry / Aufräumen verwaister `active`-Sessions (später).
