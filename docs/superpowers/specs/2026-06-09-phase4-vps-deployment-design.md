# Spec — Phase 4: VPS-Deployment

**Stand:** 2026-06-09
**Branch:** `worktree-session-multitenancy`
**Roadmap-Phase:** 4 (siehe `docs/superpowers/ROADMAP-session-app.md`)
**Status:** Design abgenommen, bereit für Implementierungsplan

---

## Ziel

Das Backend läuft heute lokal (Laptop) und wird über einen Cloudflare-Tunnel
unter `api.live-faktencheck.de` erreichbar gemacht; das Frontend liest in
Production statische JSON-Dateien. Phase 4 verlegt das Backend **dauerhaft auf
den Hostinger-VPS** (immer an, kein lokaler Start) und stellt das Frontend von
Static-Mode auf **Live-API** um. Der Export-/Static-Workflow entfällt.

**Kern-Schmerzpunkt, den diese Phase löst:** „muss lokal starten".

---

## Festgestellter Ist-Zustand (Recherche am 2026-06-09)

### VPS (`hostinger`, 72.61.83.151)
- Ubuntu 24.04 LTS, root-Zugang, x86_64, 7.8 GB RAM, 77 GB frei.
- **Docker installiert und in Benutzung** — gehört zu **NanoClaw** (eigenes,
  unabhängiges Projekt). NanoClaws **Traefik** belegt die Ports **80/443**,
  zusätzlich laufen ein Postgres-Container und eine Node-App (Port 3000).
- `uv`, `nginx`, `caddy`, `cloudflared`, `certbot` sind **nicht** installiert.
- `git`, `systemctl`, `ufw` vorhanden.

### NanoClaws Traefik
- Konfiguriert **nur** über den Docker-Provider
  (`--providers.docker=true`, `exposedbydefault=false`), **kein File-Provider**.
- Let's-Encrypt-HTTP-Challenge, ACME-Storage in einem Docker-Volume.
- Konsequenz: Eine Mitnutzung würde unser Backend zwingen, ein Docker-Container
  in Traefiks Netz mit Labels zu sein → Kopplung an NanoClaw. **Bewusst verworfen.**

### Bestehender Tunnel (lokal)
- Named Tunnel `faktencheck-api`, ID `b18ee8aa-2ea2-4632-abe8-2ab716829574`.
- Credentials + `cert.pem` unter `~/.cloudflared/` (Laptop).
- Ingress: `api.live-faktencheck.de` → `http://localhost:5000`.
- Der CNAME `api.live-faktencheck.de` zeigt bereits auf diesen Tunnel
  → **keine DNS-Änderung nötig**, nur der Ort, an dem `cloudflared` läuft, ändert sich.

### Datenbank (lokal)
- `backend/data/factcheck.db`, 241 `fact_checks`, **noch keine `sessions`-Tabelle**
  (DB ist älter als die Phase-1-Migration). Die Phase-1-Migration läuft
  idempotent beim Startup → erzeugt `sessions` und seedet Legacy-Episoden.

### Frontend Static-Mode (zu entfernen)
- `frontend/src/services/api.js`: `isStaticMode = import.meta.env.PROD && !isLocalhost`.
- `frontend/src/hooks/useShows.js`: lädt `/data/shows.json` im Static-Mode.
- `frontend/src/pages/TrustedDomainsPage.jsx`: `/data/trusted-domains.json`.
- `frontend/src/pages/FactCheckPage.jsx`: lädt `/data/<episode>.json`, eigener
  `isStaticMode`-State, mehrere abhängige Effekte.
- `frontend/src/pages/HomePage.jsx`: `isProduction`-Zweig.

---

## Gewählter Ansatz — Option A: systemd + cloudflared (kein Docker)

Begründung der Wahl (Alternativen siehe „Verworfene Alternativen"):

- **Volle Isolation von NanoClaw.** Backend nutzt weder Traefik noch die
  Host-Ports 80/443. NanoClaw könnte gelöscht/umgebaut werden, ohne das
  Fact-Check-Backend zu beeinflussen.
- **Einfachster Weg, der isoliert bleibt.** Kein Docker, kein Reverse-Proxy,
  keine Zertifikatsverwaltung. TLS erledigt Cloudflare am Tunnel.
- **Wiederverwendung des bestehenden Tunnels** → keine DNS-/Cert-Arbeit.

### Zielarchitektur auf dem VPS

Zwei schlanke **systemd-Services**, beide `enable`d (Reboot-fest), beide isoliert:

1. **`factcheck-backend.service`**
   - Startet das FastAPI-Backend mit **uv**:
     `uv run uvicorn backend.app:app --host 127.0.0.1 --port 5000`
   - **Einzelprozess, kein `--reload`, kein `--workers > 1`.**
     Harte Anforderung: `backend/state.py` hält `pending_claims`, den
     Fact-Check-Cache, den Queue-Worker und `pipeline_events` im
     Prozess-Speicher. Mehrere Worker würden divergieren. Parallelität bleibt
     über die bestehende asyncio-Semaphore (`FACT_CHECK_MAX_CONCURRENCY`) geregelt.
   - Lauscht nur auf `127.0.0.1:5000` (nicht öffentlich; nur der Tunnel erreicht es).
   - `EnvironmentFile=` zeigt auf `.env` mit den API-Keys (nur auf dem VPS, nie in git).
   - `WorkingDirectory` = Repo-Root (Imports `from config import …` und `backend.app`).
   - `Restart=always`.

2. **`cloudflared` (als Service via `cloudflared service install`)**
   - Nutzt den **bestehenden** Tunnel `faktencheck-api`.
   - Credentials-JSON + `config.yml` werden vom Laptop auf den VPS kopiert
     (`/etc/cloudflared/` oder `~/.cloudflared/`), Ingress unverändert
     `api.live-faktencheck.de` → `http://localhost:5000`.
   - `Restart` durch systemd, Reboot-fest.

**Tunnel-Cutover:** Ein Named Tunnel sollte an genau einer Stelle laufen.
Nach Umzug auf den VPS wird der **lokale** Tunnel stillgelegt
(`start/stop_production.sh`-Tunnel-Logik entfällt; lokale Credentials können
nach erfolgreicher Verifikation gelöscht werden).

### Diagramm

```
Internet
  │  https://api.live-faktencheck.de
  ▼
Cloudflare (DNS + TLS + Tunnel-Endpoint)
  │  privater Tunnel (keine offenen Ports am VPS)
  ▼
VPS:  cloudflared.service ──► 127.0.0.1:5000 ──► factcheck-backend.service (uvicorn, 1 Prozess)
                                                      │
                                                      ▼
                                              backend/data/factcheck.db (SQLite, WAL)

(NanoClaw: Traefik:80/443 + Container — komplett getrennt, kein Berührungspunkt)
```

---

## Datenmigration & Secrets

- **Repo auf den VPS:** `git clone` (nach Merge dieses Branches nach `main`).
- **DB-Migration (einmalig):** `scp backend/data/factcheck.db` →
  `<repo>/backend/data/factcheck.db` auf dem VPS **vor dem ersten Start**.
  Beim ersten Boot legt die idempotente Phase-1-Migration die `sessions`-Tabelle
  an und seedet Legacy-Episoden → alle 241 Legacy-Fact-Checks werden live serviert.
- **`.env`:** vom Laptop auf den VPS kopieren (API-Keys); nie committen.
  `LOG_LEVEL`/`FACT_CHECK_MAX_CONCURRENCY` etc. wie gehabt.
- **DB-Backup:** dokumentierter, minimaler Cron-Job
  (`sqlite3 factcheck.db ".backup '<dated>.db'"`) in `docs/deployment.md`.

---

## Frontend-Cleanup (voller Scope)

- **`VITE_BACKEND_URL=https://api.live-faktencheck.de`** in den Cloudflare-Pages-
  Umgebungsvariablen setzen; Frontend liest immer die Live-API.
- **Static-Mode komplett entfernen:**
  - `isStaticMode` aus `api.js`.
  - `/data/*.json`-Zweige in `useShows.js`, `TrustedDomainsPage.jsx`,
    `FactCheckPage.jsx` (inkl. lokalem `isStaticMode`-State + abhängige Effekte).
  - Dabei auch die toten `health.current_episode`-Referenzen entfernen
    (Phase 1 hat das globale `current_episode` abgeschafft) in `useShows.js`
    und `FactCheckPage.jsx`.
  - **Nicht** Teil von Phase 4: Der `isProduction`-**Layout**-Zweig in
    `HomePage.jsx` ist kein Static-Daten-Zweig (beide Zweige nutzen `useShows`,
    keiner liest `/data/`). Das ist eine Präsentations-/IA-Frage und gehört zu
    Phase 1b. `HomePage.jsx` braucht in Phase 4 keine Änderung.
  - `FactCheckPage.jsx`: `isLocalhost`/`showAdminMode`/`?admin=true` bleiben
    unverändert (lokal berechnet, nicht aus `api.js` importiert) — Admin-Gating
    ist von der Static-Entfernung nicht betroffen.
- **Export-/Static-Workflow löschen:**
  - `export_episode.py`
  - `frontend/public/data/*.json` (Legacy-Episode-JSONs, `shows.json`,
    `trusted-domains.json`)
  - `publish_episode.sh`, `start_production.sh`, `stop_production.sh`,
    `.current_episode`-Plumbing.
- **Zu prüfen bei der Umsetzung (Gotcha):** Der öffentliche Shows-Listen-Endpoint
  (`/api/config/shows`) muss **nur Legacy-/veröffentlichte Sessions** zurückgeben,
  nicht private User-Sessions. Falls nötig kleiner Filter-Fix. Das tiefere
  Homepage-Redesign ist Phase 1b und **nicht** Teil dieser Phase.
- **Doku aktualisieren:** `CLAUDE.md`, `docs/live-workflow.md`,
  `docs/development-workflow.md` auf den neuen Deploy-Flow umstellen
  (Export-Workflow raus). Neues `docs/deployment.md` mit VPS-Setup +
  Update-Flow + Backup.

---

## Deploy-/Update-Workflow

- **Erstinstallation (dokumentiert in `docs/deployment.md`):**
  1. `uv` auf dem VPS installieren (steht noch nicht zur Verfügung).
  2. Repo klonen, `.env` + `factcheck.db` kopieren.
  3. systemd-Units installieren + `enable --now`.
  4. cloudflared-Credentials kopieren, `cloudflared service install`.
  5. Lokalen Tunnel stilllegen.
- **Updates (`deploy.sh`, vom Laptop über SSH):**
  `ssh hostinger 'cd <repo> && git pull && uv sync && systemctl restart factcheck-backend'`.

---

## Verifikation & Rollback

- **Tests grün:** `uv run pytest -m "not integration"` (bestehende 181 Unit-Tests),
  `uv run ruff check backend/`, `cd frontend && bun run build` (nach Static-Entfernung).
- **Post-Deploy-Smoke-Test:**
  - `curl https://api.live-faktencheck.de/api/health` → liefert `active_sessions`.
  - Eine Legacy-Episode im Browser über die Live-API laden.
  - Eine neue Session end-to-end durchspielen.
- **Rollback:** Git-Tag vor dem Cutover. Bei VPS-Problemen den Frontend-Commit
  reverten (Static-Mode kehrt zurück) und den lokalen Tunnel weiterbetreiben,
  solange die lokalen Credentials noch existieren.

---

## Explizit zurückgestellt / Risiken

- **Keine Auth auf dem öffentlichen Backend.** Sobald das Backend erreichbar ist,
  kann jeder, der die API findet, kostenpflichtige Pipelines auslösen
  (AssemblyAI/Gemini/Tavily). **Risiko bewusst akzeptiert** bis Phase 3
  (Zugangscodes). Vertretbar, solange die Domain nicht beworben wird. Die
  `FACT_CHECK_MAX_CONCURRENCY`-Semaphore begrenzt nur die Parallelität, nicht die
  Gesamtkosten.
- **Admin-Gating bleibt rein client-seitig** (`?admin=true`) — wird ebenfalls in
  Phase 3 adressiert.
- **Homepage-/IA-Redesign** ist Phase 1b, nicht Teil von Phase 4.

---

## Verworfene Alternativen

- **Option B — NanoClaws Traefik mitnutzen:** Da Traefik nur den Docker-Provider
  nutzt (kein File-Provider), müsste unser Backend ein Docker-Container in
  Traefiks Netz mit Labels werden → Docker zurück + Netz-/Cert-Kopplung an
  NanoClaw. Schwerer und stärker gekoppelt als Option A.
- **Eigener Caddy/nginx oder zweiter Traefik:** Scheitert am Port-Konflikt —
  80/443 sind von NanoClaws Traefik belegt; nur ein Prozess kann einen Host-Port
  binden. Ein zweiter Reverse-Proxy bräuchte eine zweite öffentliche IP oder
  SNI-Demux über NanoClaws Traefik (mehr Kopplung).
- **Cloudflare-Proxy (orange cloud) auf Alternativport:** Bräuchte Origin-Rule +
  offenen Port; mehr Fummelei als der Tunnel, keine bessere Isolation.
- **Railway statt VPS:** Technisch tragfähig (persistenter Container, Volume für
  SQLite, single instance), aber laufende Kosten für etwas, das der bereits
  bezahlte, größtenteils ungenutzte VPS abdeckt. Als Escape-Hatch später leicht
  möglich (containerisierte App).
- **Docker (ein Container) + cloudflared:** Möglich, aber Docker bringt keinen
  Vorteil gegenüber dem schlanken systemd-Service und fügt Build-/Image-Overhead hinzu.
