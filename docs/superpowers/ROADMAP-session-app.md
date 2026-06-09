# Roadmap — Von „Live Faktencheck" zur Multi-User-App

**Stand:** 2026-06-09
**Branch dieser Arbeit:** `worktree-session-multitenancy` (Phase 1, abgeschlossen)

Dieses Dokument hält den Gesamtplan und die bereits getroffenen Entscheidungen fest,
damit die Arbeit später nahtlos fortgesetzt werden kann. Jede Phase bekommt einen
eigenen Spec → Plan → Implementierungs-Zyklus (Brainstorming-Workflow).

---

## Vision

Aus dem heutigen Single-Operator-System (lokales Backend, hartkodierte Episode, ein
Moderator) eine **gehostete App** machen, bei der **viele Nutzer parallel eigene
Live-Faktencheck-Sessions** fahren — Audio per Browser-Mikrofon, Selbst-Moderation,
Ergebnisse privat per Link teilbar.

## Festgelegte Rahmenentscheidungen (gelten phasenübergreifend)

- **Zielgruppe:** breite Öffentlichkeit (Journalisten waren nur ein Beispiel).
- **Audio-Quelle:** Browser-Mikrofon (Desktop + Handy). Tab-/System-Audio via
  Bildschirm-Sharing optional später (ersetzt das lokale BlackHole).
- **Moderation:** jeder Nutzer moderiert seine eigene Session selbst (Human-in-the-Loop).
- **Zugang:** vorerst per Zugangscode (kein offenes Registrierungssystem).
- **Sichtbarkeit:** neue Sessions sind privat, nur per Link abrufbar. Die bestehenden
  veröffentlichten Episoden bleiben als Legacy öffentlich.
- **Hosting:** vorhandener Hostinger-VPS (dauerhafter Prozess, gut für Live-Audio —
  bewusst KEIN Serverless wie wahl.chat, das ist nur für zustandslose Chatbots optimal).
- **Frontend bleibt** React+Vite auf Cloudflare Pages; Domain `live-faktencheck.de`
  bei Cloudflare. Kein Next.js-Wechsel (lohnt nicht).
- **DB bleibt SQLite** (Single-Writer + WAL reicht bei wenigen parallelen Sessions;
  Postgres erst bei vielen gleichzeitigen Schreibern neu bewerten). Persistenz ist mit
  Multi-Tenancy wichtiger, nicht unwichtiger.
- **Architektur:** Chunk-POST + Polling beibehalten (kein WebSocket-Rewrite).

---

## Phasenübersicht

| Phase | Inhalt | Status |
|-------|--------|--------|
| **1** | Backend-Multi-Tenancy (Sessions statt globaler Episode) | ✅ **Abgeschlossen** |
| **1b** | Homepage / App-Informationsarchitektur neu denken | ⬜ Offen (eigener Spec) |
| **2** | Browser-Audio-Capture (ersetzt `listener.py`) | ⬜ Offen |
| **3** | Zugangscodes + Kosten-/Missbrauchslimits | ⬜ Offen |
| **4** | VPS-Deployment (kein lokaler Start, JSON-Export entfällt) | 🟡 Backend live auf VPS; Go-Live-Merge offen |

---

## ✅ Phase 1 — Session-Multi-Tenancy (ABGESCHLOSSEN)

**Spec:** `docs/superpowers/specs/2026-06-09-session-multitenancy-design.md`
**Plan:** `docs/superpowers/plans/2026-06-09-session-multitenancy.md`

**Was gebaut wurde:**
- Neue `sessions`-DB-Tabelle + CRUD; aus „Episode" wird eine zur Laufzeit erzeugte
  DB-Session. Spalte `episode_key` → `session_id` (idempotente Migration).
- Legacy-`EPISODES` werden beim Startup als öffentliche Sessions geseedet
  (`session_id == alter episode_key`, daher bleiben alte Fact-Checks 1:1 erhalten).
- `Episode.from_session_row` / `episode_to_session_dict` Mapping-Helfer.
- Sessions-Router: `POST /api/sessions`, `GET /api/sessions/{id}`, `POST /api/sessions/{id}/end`.
- Alle Router (audio, claims, fact_checks, config) + `pipeline.py`-Retrigger nach
  `session_id` gescoped. Globaler `current_episode_key` entfernt. `POST /set-episode`
  entfernt. `/api/health` liefert `active_sessions`.
- Queue-Worker-Concurrency (`asyncio.Semaphore`) unverändert; Items tragen `session_id`.
- Frontend: „Session anlegen"-Formular (`/new`), `session_id`-Scoping, teilbarer
  Link `/{session_id}`.
- `listener.py` sendet `session_id` (statt `episode_key`; `set-episode`-Aufruf entfernt).
- 181 Unit-Tests grün, inkl. Isolations-Regressionstest (zwei Sessions sehen sich nicht).

**Ergebnis:** Viele Sessions können parallel und isoliert laufen. Backend ist
multi-tenant-fähig.

---

## ⬜ Phase 1b — Homepage / Informationsarchitektur

**Warum:** Sobald Sessions privat/per-Link sind, verliert die Startseite ihren
„Schaufenster"-Zweck (Live-Faktenchecks präsentieren). Sie braucht eine neue Aufgabe.

**Offene Designfragen (für Brainstorming):**
- Was ist die primäre Aufgabe der Startseite? Wahrscheinlich: Produkt erklären +
  Einstieg „Eigene Session starten" (Code eingeben → Session-Formular).
- Wie werden die Legacy-Episoden (öffentlich) künftig dargestellt — eigener
  „Beispiele/Archiv"-Bereich?
- Navigation/IA der ganzen App: Create-Flow, Live-Ansicht, geteilte Link-Ansicht,
  Archiv, About.
- Visual-Companion (Mockups) bietet sich hier an, da stark visuell.

**Abhängigkeiten:** keine harten; kann unabhängig von Phase 2–4 entworfen werden.
In Phase 1 wurde die Homepage bewusst NICHT angefasst (nur `/new` ergänzt).

---

## ⬜ Phase 2 — Browser-Audio-Capture

**Ziel:** `listener.py` durch Browser-Aufnahme ersetzen. Der Browser nimmt das
Mikrofon (Desktop/Handy) in festen Blöcken auf und POSTet sie an `/api/audio-block`
mit `session_id` — exakt das Contract, das `listener.py` heute schon nutzt.

**Technische Eckpunkte:**
- `MediaRecorder`-API im Browser; Aufnahme in N-Sekunden-Chunks, Upload als
  multipart an den bestehenden Audio-Block-Endpunkt. Kein WebSocket nötig.
- Backend-seitig ist nichts Großes nötig — der Endpunkt existiert und ist
  session-scoped. Ggf. Audioformat-Handling (WebM/Opus vom Browser vs. WAV) prüfen:
  AssemblyAI akzeptiert mehrere Formate; Transkriptions-Service ggf. anpassen.
- UI: „Aufnahme starten/stoppen" auf der Live-Seite der Session; Statusanzeige der
  Pipeline-Events (existiert: `/api/pipeline-status`).
- Optional/später: Tab-/System-Audio via `getDisplayMedia({audio:true})` für Shows,
  die im Web laufen (BlackHole-Ersatz).

**Abhängigkeiten:** Phase 1 (Session-Scoping) — erfüllt.

---

## ⬜ Phase 3 — Zugangscodes + Limits

**Ziel:** Session-Erstellung gaten und Kosten/Missbrauch begrenzen.

**Technische Eckpunkte:**
- Code-Tabelle (Code → gültig/Kontingent). `POST /api/sessions` verlangt einen
  gültigen Code; das Feld `owner_code` der `sessions`-Tabelle wird damit befüllt
  (Spalte existiert bereits, wird in Phase 1 noch nicht gesetzt).
- Hinweis: `owner_code` wird aktuell aus der `/api/config/{session_id}`-Antwort
  herausgefiltert (kein Leak) — beim Einführen echter Codes diesen Filter beibehalten.
- Limits: Anzahl/Dauer Sessions pro Code, Deckelung der API-Calls
  (Transkription/Gemini/Tavily). Bestehende `FACT_CHECK_MAX_CONCURRENCY`-Semaphore
  begrenzt schon die globale Parallelität.
- Optional: einfache Admin-Sicht zum Codes-Verwalten.

**Abhängigkeiten:** Phase 1 (`owner_code`-Spalte, Sessions-Router) — erfüllt.

---

## 🟡 Phase 4 — VPS-Deployment (Backend live; Go-Live-Merge offen)

**Status (2026-06-09):** Part A (Code) + Part B (Betrieb) abgeschlossen auf Branch
`worktree-session-multitenancy`. Das Backend läuft live auf dem VPS als zwei systemd-Services
(`factcheck-backend` + `cloudflared`); `https://api.live-faktencheck.de/api/health` liefert
`status: ok`, `fact_checks: 241`, übersteht Reboots, tägliches DB-Backup-Cron aktiv. CLI-
verifiziert: `/api/config/shows` (nur public), `/api/trusted-domains`, CORS für `*.pages.dev`.
**Offen:** Pages-**Preview**-Smoke-Test im Browser (Cloudflare-Dashboard-Schritte) und der
optionale **Go-Live-Merge** nach `main` (schaltet das Prod-Frontend auf die Live-API um).
Tunnel bleibt bewusst bestehen (Option A) — der ursprünglich geplante DNS-A-Record entfällt.
Details: `plans/2026-06-09-phase4-vps-deployment.md`, Handover `handover/2026-06-09_*`.

**Ziel:** Backend dauerhaft auf dem Hostinger-VPS — kein lokaler Start.

**Technische Eckpunkte:**
- Backend als `systemd`-Service (oder Docker) auf dem VPS; eigene öffentliche IP.
- DNS: `api.live-faktencheck.de` als A-Record auf die VPS-IP (Tunnel löschen).
  TLS via Caddy/nginx + Let's Encrypt oder Cloudflare-Proxy.
- Frontend bleibt auf Cloudflare Pages; nur `VITE_BACKEND_URL` zeigt auf die neue API.
- CORS in `backend/app.py` ggf. anpassen.
- **JSON-Export entfällt:** Sobald das Backend erreichbar ist, liest das Frontend live
  über die API. `export_episode.py` und der Re-Export-Workflow werden überflüssig
  (siehe Spec §2a). Cleanup als Teil dieser Phase.
- `start_production.sh` / Tunnel-Setup-Doks anpassen oder ersetzen.

**Abhängigkeiten:** unabhängig; kann jederzeit nach Phase 1 erfolgen. Sinnvoll früh,
da es den ursprünglichen Schmerzpunkt („muss lokal starten") direkt löst.

---

## Empfohlene Reihenfolge

1. **Phase 4 (Deployment)** — löst den Kern-Schmerz sofort, unabhängig vom Rest.
2. **Phase 2 (Browser-Audio)** — macht die App ohne lokales `listener.py` nutzbar.
3. **Phase 3 (Zugangscodes)** — vor öffentlichem Rollout, zur Kostenkontrolle.
4. **Phase 1b (Homepage/IA)** — begleitend/zum Schluss, wenn die Flows stehen.

(Reihenfolge ist nicht zwingend; 1b kann parallel entworfen werden.)

## Wiedereinstieg

- Diesen Branch auschecken: `git checkout worktree-session-multitenancy`
  (bzw. der Worktree unter `.claude/worktrees/session-multitenancy`).
- Für die nächste Phase: Brainstorming-Skill → Spec nach
  `docs/superpowers/specs/` → Plan nach `docs/superpowers/plans/`.
