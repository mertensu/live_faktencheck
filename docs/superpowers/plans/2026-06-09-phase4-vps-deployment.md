# Phase 4: VPS-Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the backend permanently onto the Hostinger VPS (always-on, no local start) behind the existing Cloudflare Tunnel, switch the frontend from static-mode to the live API, and delete the export/static workflow.

**Architecture:** Two isolated systemd services on the VPS — `factcheck-backend` (`uv run uvicorn`, single process) and `cloudflared` (reusing the existing `faktencheck-api` tunnel). No Docker, no host ports, fully separated from NanoClaw's Traefik. The frontend always reads `https://api.live-faktencheck.de`.

**Tech Stack:** FastAPI + uvicorn, uv, SQLite (WAL), systemd, cloudflared, React/Vite on Cloudflare Pages.

**Spec:** `docs/superpowers/specs/2026-06-09-phase4-vps-deployment-design.md`

**Key facts (verified 2026-06-09):**
- VPS `hostinger` = 72.61.83.151, Ubuntu 24.04, root, Docker present (NanoClaw), `uv`/`cloudflared` absent.
- Tunnel `faktencheck-api`, ID `b18ee8aa-2ea2-4632-abe8-2ab716829574`; local creds in `~/.cloudflared/`; ingress already → `api.live-faktencheck.de`. No DNS change needed.
- Local DB `backend/data/factcheck.db` = 241 fact_checks, no `sessions` table yet (Phase-1 migration runs idempotently at startup).
- No frontend test framework → frontend tasks are verified by `bun run build` + a grep gate.

---

## PART A — Code changes (on branch `worktree-session-multitenancy`)

### Task 1: Backend — `/api/config/shows` returns only public sessions

**Why:** In static mode the frontend read a pre-filtered `shows.json`. Going live, `/api/config/shows` currently returns *all* sessions (incl. private user sessions) via `db.list_sessions()`. The public homepage must only show public/legacy sessions.

**Files:**
- Modify: `backend/routers/config.py:28-48`
- Test: `backend/tests/test_api_config.py`

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_api_config.py`:

```python
async def test_shows_excludes_private_sessions(client):
    db = state.get_db()
    await db.add_session({"session_id": "pub1", "title": "maischberger", "visibility": "public"})
    await db.add_session({"session_id": "priv1", "title": "user session", "visibility": "private"})
    resp = await client.get("/api/config/shows")
    assert resp.status_code == 200
    keys = [s["key"] for s in resp.json()["shows"]]
    assert "pub1" in keys
    assert "priv1" not in keys
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_api_config.py::test_shows_excludes_private_sessions -v`
Expected: FAIL — `assert "priv1" not in keys` (private session currently included).

- [ ] **Step 3: Implement the filter** — in `backend/routers/config.py`, change the comprehension in `get_all_shows_endpoint` to skip non-public sessions:

```python
        detailed = sorted(
            [
                {
                    "key": s["session_id"],
                    "name": get_show_name(s["title"]),
                    "date": s.get("date"),
                    "episode_name": Episode.from_session_row(s).episode_name,
                    "type": s.get("type", "show"),
                    "publish": True,
                }
                for s in sessions
                if s.get("visibility") == "public"
            ],
            key=lambda x: x["key"], reverse=True,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_api_config.py -v`
Expected: PASS (both `test_shows_lists_seeded_session` and the new test).

- [ ] **Step 5: Commit**

```bash
git add backend/routers/config.py backend/tests/test_api_config.py
git commit -m "Backend: /api/config/shows returns only public sessions"
```

---

### Task 2: Frontend — remove static-mode flag from `api.js`

**Files:**
- Modify: `frontend/src/services/api.js:10-14`

- [ ] **Step 1: Remove the static-mode block** — delete these lines from `frontend/src/services/api.js`:

```js
// Static mode: production build not running on localhost
const isLocalhost = window.location.hostname === 'localhost' ||
  window.location.hostname === '127.0.0.1' ||
  window.location.hostname.startsWith('192.168.')
export const isStaticMode = import.meta.env.PROD && !isLocalhost
```

(Leave `BACKEND_URL`, `N8N_VERIFIED_WEBHOOK`, `debug`, `FETCH_HEADERS`, etc. untouched.)

- [ ] **Step 2: Verify no other code in api.js references the removed symbols**

Run: `grep -n "isStaticMode\|isLocalhost" frontend/src/services/api.js`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.js
git commit -m "Frontend: remove isStaticMode from api.js"
```

---

### Task 3: Frontend — `useShows.js` reads live API only

**Why:** Drop the `/data/shows.json` branch and the dead `health.current_episode` reference (Phase 1 removed global current_episode; `liveKey` is always null now).

**Files:**
- Modify: `frontend/src/hooks/useShows.js`

- [ ] **Step 1: Replace the whole file** with the live-only version:

```js
import { useState, useEffect } from 'react'
import { BACKEND_URL, FETCH_HEADERS, safeJsonParse, debug } from '../services/api'

export function useShows() {
  const [shows, setShows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()

    const loadShows = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/config/shows`, {
          headers: FETCH_HEADERS,
          signal: controller.signal
        })
        if (!response.ok) throw new Error(`Failed to load shows: ${response.status}`)
        const data = await safeJsonParse(response, 'Error loading shows')
        if (data?.shows?.length > 0) {
          setShows(data.shows)
        }
        setError(null)
      } catch (err) {
        if (err.name !== 'AbortError') {
          debug.error('Error loading shows:', err)
          setError(err)
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    loadShows()

    return () => controller.abort()
  }, [])

  return { shows, loading, error }
}
```

- [ ] **Step 2: Verify no static/dead references remain**

Run: `grep -n "isStaticMode\|/data/\|current_episode" frontend/src/hooks/useShows.js`
Expected: no output.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useShows.js
git commit -m "Frontend: useShows reads live API only"
```

---

### Task 4: Frontend — `TrustedDomainsPage.jsx` reads live API only

**Files:**
- Modify: `frontend/src/pages/TrustedDomainsPage.jsx:2,8-12`

- [ ] **Step 1: Change the import** (line 2) from:

```js
import { BACKEND_URL, isStaticMode, safeJsonParse } from '../services/api'
```
to:
```js
import { BACKEND_URL, safeJsonParse } from '../services/api'
```

- [ ] **Step 2: Replace the URL logic** — change the effect body from:

```js
    const url = isStaticMode
      ? '/data/trusted-domains.json'
      : `${BACKEND_URL}/api/trusted-domains`
    fetch(url)
```
to:
```js
    fetch(`${BACKEND_URL}/api/trusted-domains`)
```

- [ ] **Step 3: Verify no static references remain**

Run: `grep -n "isStaticMode\|/data/" frontend/src/pages/TrustedDomainsPage.jsx`
Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/TrustedDomainsPage.jsx
git commit -m "Frontend: TrustedDomainsPage reads live API only"
```

---

### Task 5: Frontend — remove static-mode from `FactCheckPage.jsx`

**Why:** Make the page always load config + poll the live API. `isLocalhost`/`showAdminMode`/`?admin=true` stay (admin gating is unaffected; `isLocalhost` is computed locally, not imported).

**Files:**
- Modify: `frontend/src/pages/FactCheckPage.jsx`

- [ ] **Step 1: Remove the `isStaticMode` state declaration** (around line 68-70). Delete:

```js
  // Static mode: production build on non-localhost → try /data/<episode>.json first,
  // fall back to live polling if no static file exists (live session in progress)
  const [isStaticMode, setIsStaticMode] = useState(isProduction && !isLocalhost)
```

- [ ] **Step 2: Delete the entire static-data-loading effect** (the `useEffect` that does `fetch(\`/data/${key}.json\`)`, ~lines 112-145, including its dependency array `}, [isStaticMode, isAdminMode, episodeKey, showKey, showName])`). This whole block is removed.

- [ ] **Step 3: Remove the `if (isStaticMode) return` guard** from the config-load effect (the line right after `const controller = new AbortController()` is preceded by `if (isStaticMode) return`). Delete that single guard line so config always loads. Also remove `isStaticMode` from that effect's dependency array (`}, [showName, showKey, episodeKey, isStaticMode]` → `}, [showName, showKey, episodeKey]`).

- [ ] **Step 4: Remove the `if (isStaticMode) return` guard** from the fact-checks polling effect (the line `if (isStaticMode) return` after `if (isAdminMode) return`). Delete it. If `isStaticMode` appears in that effect's dependency array, remove it there too.

- [ ] **Step 5: Verify ALL static references are gone from the file**

Run: `grep -n "isStaticMode\|setIsStaticMode\|/data/\|current_episode" frontend/src/pages/FactCheckPage.jsx`
Expected: no output. (If any line remains — e.g. another dep array — remove it.)

- [ ] **Step 6: Verify admin gating is intact**

Run: `grep -n "showAdminMode\|isLocalhost\|forceAdmin" frontend/src/pages/FactCheckPage.jsx`
Expected: `isLocalhost`, `showAdminMode`, `forceAdmin` still present and unchanged.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/FactCheckPage.jsx
git commit -m "Frontend: FactCheckPage always uses live API (remove static mode)"
```

---

### Task 6: Frontend build + repo-wide static gate

**Files:** none (verification only)

- [ ] **Step 1: Repo-wide grep gate** — no static-mode leftovers anywhere in frontend source:

Run: `grep -rn "isStaticMode\|/data/\|current_episode" frontend/src`
Expected: no output.

- [ ] **Step 2: Build the frontend**

Run: `cd frontend && bun install && bun run build`
Expected: build succeeds, no errors about undefined `isStaticMode`.

- [ ] **Step 3: Commit** (only if `bun.lock`/build config changed; otherwise skip)

```bash
git add -A && git commit -m "Frontend: verify build after static-mode removal" || echo "nothing to commit"
```

---

### Task 7: Delete the export/static workflow

**Files:**
- Delete: `export_episode.py`
- Delete: `publish_episode.sh`, `start_production.sh`, `stop_production.sh`
- Delete: `frontend/public/data/` (all static JSONs: legacy episode JSONs, `shows.json`, `trusted-domains.json`)

- [ ] **Step 1: Confirm nothing imports `export_episode`**

Run: `grep -rn "export_episode" --include="*.py" . | grep -v "^Binary"`
Expected: no output (besides possibly docs, which Task 8 handles).

- [ ] **Step 2: Delete the files**

```bash
git rm export_episode.py publish_episode.sh start_production.sh stop_production.sh
git rm -r frontend/public/data
rm -f .current_episode
```

- [ ] **Step 3: Verify backend/tests still pass** (nothing referenced the deleted script)

Run: `uv run pytest backend/tests -m "not integration" -q`
Expected: all pass (181+ tests).

- [ ] **Step 4: Commit**

```bash
git commit -m "Remove static-export workflow (export script, production scripts, static JSON)"
```

---

### Task 8: Deployment artifacts + docs

**Files:**
- Create: `deploy/factcheck-backend.service`
- Create: `deploy/cloudflared-config.yml`
- Create: `deploy/deploy.sh`
- Create: `docs/deployment.md`
- Modify: `CLAUDE.md`, `docs/live-workflow.md`, `docs/development-workflow.md`

- [ ] **Step 1: Create `deploy/factcheck-backend.service`**

```ini
[Unit]
Description=Live Faktencheck Backend (FastAPI/uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/fact_check
EnvironmentFile=/opt/fact_check/.env
# Single process required: backend/state.py holds in-memory state (no --workers, no --reload)
ExecStart=/root/.local/bin/uv run uvicorn backend.app:app --host 127.0.0.1 --port 5000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 2: Create `deploy/cloudflared-config.yml`** (goes to `/etc/cloudflared/config.yml` on the VPS)

```yaml
tunnel: faktencheck-api
credentials-file: /etc/cloudflared/b18ee8aa-2ea2-4632-abe8-2ab716829574.json

ingress:
  - hostname: api.live-faktencheck.de
    service: http://localhost:5000
  - service: http_status:404
```

- [ ] **Step 3: Create `deploy/deploy.sh`** (run from the laptop for code updates)

```bash
#!/bin/bash
# Update the deployed backend on the VPS: pull, sync deps, restart service.
set -e
VPS=hostinger
REPO=/opt/fact_check
ssh "$VPS" "cd $REPO && git pull && /root/.local/bin/uv sync && systemctl restart factcheck-backend && systemctl --no-pager status factcheck-backend | head -5"
echo "Smoke test:"
curl -fsS https://api.live-faktencheck.de/api/health && echo
```

- [ ] **Step 4: Make deploy.sh executable and create `docs/deployment.md`**

```bash
chmod +x deploy/deploy.sh
```

`docs/deployment.md` content:

```markdown
# Deployment (VPS)

The backend runs permanently on the Hostinger VPS (`hostinger`, 72.61.83.151) as two
systemd services. The frontend is on Cloudflare Pages and reads the live API at
`https://api.live-faktencheck.de`. There is no local start and no static-JSON export.

## Architecture
- `factcheck-backend.service` — `uv run uvicorn backend.app:app` on 127.0.0.1:5000, single process.
- `cloudflared` — reuses the named tunnel `faktencheck-api`; maps `api.live-faktencheck.de` → localhost:5000.
- Both are isolated from NanoClaw (no Docker, no ports 80/443).

## First-time provisioning (run on the VPS as root)
1. Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. `git clone https://github.com/mertensu/live_faktencheck.git /opt/fact_check`
3. Copy secrets/data from laptop:
   - `scp .env hostinger:/opt/fact_check/.env`
   - `scp backend/data/factcheck.db hostinger:/opt/fact_check/backend/data/factcheck.db`
4. `cd /opt/fact_check && /root/.local/bin/uv sync`
5. Install backend service:
   - `cp deploy/factcheck-backend.service /etc/systemd/system/`
   - `systemctl daemon-reload && systemctl enable --now factcheck-backend`
   - Verify: `curl -fsS http://127.0.0.1:5000/api/health`
6. Install cloudflared + tunnel (AFTER stopping the laptop tunnel):
   - `curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cf.deb && dpkg -i /tmp/cf.deb`
   - `mkdir -p /etc/cloudflared`
   - `scp` the tunnel creds + config from laptop:
     `scp ~/.cloudflared/b18ee8aa-2ea2-4632-abe8-2ab716829574.json hostinger:/etc/cloudflared/`
     `scp deploy/cloudflared-config.yml hostinger:/etc/cloudflared/config.yml`
   - `cloudflared service install && systemctl enable --now cloudflared`
   - Verify: `curl -fsS https://api.live-faktencheck.de/api/health`

## Updating the backend
From the laptop: `./deploy/deploy.sh`

## DB backup (cron on the VPS)
`0 4 * * * sqlite3 /opt/fact_check/backend/data/factcheck.db ".backup '/opt/fact_check/backend/data/backup-$(date +\%F).db'"`
```

- [ ] **Step 5: Update `CLAUDE.md`** — in "Common Commands", remove the `start_production.sh`/`stop_production.sh`/`publish_episode.sh` lines and the "Re-run/Delete a claim" export-based workflows; add: "Production: backend runs on the VPS (see `docs/deployment.md`); update with `./deploy/deploy.sh`." Remove the `export_episode.py --json` references.

- [ ] **Step 6: Update `docs/live-workflow.md` and `docs/development-workflow.md`** — remove references to the static export / `start_production.sh` / Cloudflare Pages static JSON; point production usage to `docs/deployment.md` and the live API. (Dev workflow with `start_dev.sh` is unchanged.)

- [ ] **Step 7: Verify docs no longer reference deleted artifacts**

Run: `grep -rn "export_episode\|start_production\|stop_production\|publish_episode\|/data/shows.json" docs CLAUDE.md`
Expected: no output.

- [ ] **Step 8: Commit**

```bash
git add deploy docs CLAUDE.md
git commit -m "Add VPS deployment artifacts + docs; remove export-workflow references"
```

---

### Task 9: Push the branch (NO merge to main yet)

> Decision (2026-06-09): we do NOT merge to main during Phase 4. Instead we deploy the
> backend from the branch and verify the frontend via a Cloudflare Pages **preview**
> deployment (built from the branch). Merging to main is a separate, optional "Go-Live"
> step (see the end of this plan) done only when we're satisfied.

- [ ] **Step 1: Full test + build gate**

Run: `uv run pytest backend/tests -m "not integration" -q && uv run ruff check backend/ && (cd frontend && bun run build)`
Expected: tests pass, ruff clean, build succeeds.

- [ ] **Step 2: Tag the pre-cutover state (rollback anchor)**

```bash
git tag pre-vps-cutover
git push origin pre-vps-cutover
```

- [ ] **Step 3: Push the branch to origin**

```bash
git push -u origin worktree-session-multitenancy
```

Expected: branch pushed. If Cloudflare Pages has preview deployments enabled for
non-production branches, this triggers a **preview** build (a `*.pages.dev` URL) — this
does NOT touch production (`live-faktencheck.de` stays on the current main build).

---

## PART B — VPS deployment (operational, over SSH)

> Production is NOT merged. Deploy the backend to the VPS from the **branch**
> (`worktree-session-multitenancy`). Follow `docs/deployment.md`; the steps below are the
> executable sequence with expected output. The production site stays on the old static
> build until the optional Go-Live merge at the end.

### Task 10: Provision VPS base

- [ ] **Step 1: Install uv on the VPS**

Run: `ssh hostinger 'curl -LsSf https://astral.sh/uv/install.sh | sh && /root/.local/bin/uv --version'`
Expected: prints a `uv 0.x.y` version.

- [ ] **Step 2: Clone the BRANCH into /opt/fact_check**

> We are not merging to main yet, so clone the working branch (it must already be pushed — Task 9 Step 3).

Run: `ssh hostinger 'git clone --branch worktree-session-multitenancy https://github.com/mertensu/live_faktencheck.git /opt/fact_check && ls /opt/fact_check/backend/app.py'`
Expected: lists `app.py`.

> Later, at Go-Live (merge to main), switch the VPS checkout to main:
> `ssh hostinger 'cd /opt/fact_check && git fetch origin && git checkout main && git pull'` then `./deploy/deploy.sh`.

- [ ] **Step 3: Copy secrets + DB from laptop**

```bash
scp .env hostinger:/opt/fact_check/.env
ssh hostinger 'mkdir -p /opt/fact_check/backend/data'
scp backend/data/factcheck.db hostinger:/opt/fact_check/backend/data/factcheck.db
```
Expected: both transfers complete; `ssh hostinger 'ls -la /opt/fact_check/backend/data/factcheck.db'` shows ~640 KB.

- [ ] **Step 4: Sync Python deps**

Run: `ssh hostinger 'cd /opt/fact_check && /root/.local/bin/uv sync'`
Expected: resolves + installs the environment with no errors.

---

### Task 11: Backend systemd service

- [ ] **Step 1: Install and start the service**

```bash
ssh hostinger 'cp /opt/fact_check/deploy/factcheck-backend.service /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now factcheck-backend'
```
Expected: no error.

- [ ] **Step 2: Verify it is healthy locally on the VPS**

Run: `ssh hostinger 'sleep 3; curl -fsS http://127.0.0.1:5000/api/health'`
Expected: JSON with `"status":"ok"` and `"fact_checks":` ≥ 241 (proves the migrated DB loaded and seeding ran).

- [ ] **Step 3: Confirm migration + seeding in logs**

Run: `ssh hostinger 'journalctl -u factcheck-backend --no-pager | tail -20'`
Expected: lines incl. "Legacy episodes seeded into sessions table" and "Claim queue worker started", no tracebacks.

---

### Task 12: Tunnel cutover

> Order matters: stop the laptop tunnel BEFORE starting the VPS tunnel, so the same named tunnel never runs in two places (avoids Cloudflare load-balancing onto the dead laptop backend).

- [ ] **Step 1: Stop the laptop tunnel**

Run (laptop): `pkill -f "cloudflared.*tunnel.*run" || true; pgrep -f cloudflared || echo "laptop tunnel stopped"`
Expected: prints "laptop tunnel stopped".

- [ ] **Step 2: Install cloudflared on the VPS**

Run: `ssh hostinger 'curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cf.deb && dpkg -i /tmp/cf.deb && cloudflared --version'`
Expected: prints a cloudflared version.

- [ ] **Step 3: Copy tunnel credentials + config to the VPS**

```bash
ssh hostinger 'mkdir -p /etc/cloudflared'
scp ~/.cloudflared/b18ee8aa-2ea2-4632-abe8-2ab716829574.json hostinger:/etc/cloudflared/
scp deploy/cloudflared-config.yml hostinger:/etc/cloudflared/config.yml
```
Expected: both files present: `ssh hostinger 'ls /etc/cloudflared/'`.

- [ ] **Step 4: Install + start the cloudflared service**

Run: `ssh hostinger 'cloudflared service install && systemctl enable --now cloudflared && sleep 5 && systemctl --no-pager status cloudflared | head -5'`
Expected: service `active (running)`.

- [ ] **Step 5: Verify the API is reachable publicly**

Run: `curl -fsS https://api.live-faktencheck.de/api/health`
Expected: same JSON as Task 11 Step 2 (`status: ok`, fact_checks ≥ 241).

---

### Task 13: Cloudflare Pages PREVIEW + end-to-end smoke test (no merge)

> We verify the live-API frontend on a Pages **preview** build (from the branch) against
> the live VPS backend — without touching production. CORS already allows `*.pages.dev`
> (committed on the branch in `backend/app.py`).

- [ ] **Step 1: Set `VITE_BACKEND_URL` for the Pages PREVIEW environment** (manual, user action)

In Cloudflare Pages → project → Settings → Environment variables, ensure the **Preview**
environment has `VITE_BACKEND_URL=https://api.live-faktencheck.de`. (Pages keeps Production
and Preview env vars separate.) Also confirm preview deployments are enabled for
non-production branches. If the branch was pushed (Task 9 Step 3) before the var was set,
re-trigger the preview build (e.g. Pages dashboard → Retry deployment, or push an empty commit).
Expected: a preview deployment with a `*.pages.dev` URL.

- [ ] **Step 2: Find the preview URL**

In the Pages dashboard, open the latest deployment for branch `worktree-session-multitenancy`
and copy its URL (a `*.pages.dev` address). Production `live-faktencheck.de` is unaffected.

- [ ] **Step 3: Smoke-test the PREVIEW URL (manual)**

Against the preview `*.pages.dev` URL:
- Homepage lists the legacy/published episodes (from `/api/config/shows`), no private sessions shown.
- Open a legacy episode → fact-checks render (served live from the VPS DB, not static JSON).
- `/trusted-domains` → list loads from the live API.
- Create a new session via `/new` → returns a `session_id`, opens the live view.
- Open browser devtools → no CORS errors calling `https://api.live-faktencheck.de`.

Expected: all work against the live VPS backend from the preview origin.

- [ ] **Step 4: Reboot-resilience check**

Run: `ssh hostinger 'systemctl reboot'` then wait ~60s and run `curl -fsS https://api.live-faktencheck.de/api/health`
Expected: API responds after reboot (both services `enable`d → auto-start). 

---

### Task 14: Finalize (backup + handover)

- [ ] **Step 1: Install the DB backup cron on the VPS**

Run: `ssh hostinger 'crontab -l 2>/dev/null | { cat; echo "0 4 * * * sqlite3 /opt/fact_check/backend/data/factcheck.db \".backup '\''/opt/fact_check/backend/data/backup-\$(date +\\%F).db'\''\""; } | crontab -'`
Expected: `ssh hostinger 'crontab -l'` shows the backup line.

- [ ] **Step 2: Delete laptop tunnel credentials (optional, after a stable day)**

> Defer this until the VPS deployment has been verified stable. Removing `~/.cloudflared/` makes the laptop unable to run the tunnel (rollback then requires re-auth). Skip during the same session.

- [ ] **Step 3: Update memory + roadmap (Part B done; NOT yet Go-Live)**

- In `docs/superpowers/ROADMAP-session-app.md`, note Phase 4 backend is live on the VPS and verified via Pages preview; Go-Live (merge) still pending. Do NOT mark Phase 4 fully ✅ until the Go-Live merge.
- Do NOT yet rewrite `memory.md` "Deployment Architecture" (that still describes current production until the merge); add a Recent Changes entry instead.
- Update the handover with Part B results.

```bash
git add docs/superpowers/ROADMAP-session-app.md
git commit -m "Roadmap: Phase 4 backend live on VPS (preview-verified); Go-Live merge pending"
git push origin worktree-session-multitenancy
```

---

## Go-Live (LATER, optional) — merge to main

> Only when satisfied with the preview. This is the deliberate production switch: it makes
> Cloudflare Pages rebuild **production** (`live-faktencheck.de`) onto the live API. The VPS
> backend must already be up (Part B) — it is.

- [ ] **Step 1: Set `VITE_BACKEND_URL` for the Pages PRODUCTION environment** = `https://api.live-faktencheck.de` (if not already).

- [ ] **Step 2: Merge and push**

```bash
git checkout main
git merge --no-ff worktree-session-multitenancy -m "Phase 4: VPS deployment + live-API frontend"
git push origin main
```
Expected: Pages auto-builds production from `main`.

- [ ] **Step 3: Point the VPS at main** (so future `./deploy/deploy.sh` pulls main)

```bash
ssh hostinger 'cd /opt/fact_check && git fetch origin && git checkout main && git pull'
```

- [ ] **Step 4: Production smoke test** — repeat Task 13 Step 3 against `https://live-faktencheck.de`.

- [ ] **Step 5: Finalize** — mark Phase 4 ✅ in the roadmap; rewrite `memory.md` "Deployment Architecture" to the VPS model; update the handover.

- [ ] **Rollback (if needed):** revert the merge commit on main (`git revert -m 1 <merge-sha> && git push`) → Pages rebuilds the previous static frontend. The `pre-vps-cutover` tag marks the last pre-merge state.

---

## Self-review notes (coverage vs. spec)
- Backend single-process / no-reload → Task 8 systemd unit (ExecStart, comment).
- Tunnel reuse, no DNS change → Task 12.
- DB migration (241 fact_checks, idempotent seed) → Task 10 Step 3 + Task 11 Steps 2-3.
- Secrets on VPS only → Task 10 Step 3 (scp .env), never committed.
- Frontend static-mode removal → Tasks 2-6; export/static deletion → Task 7.
- Shows-list private-session filter (gotcha) → Task 1.
- Docs/deploy artifacts → Task 8; deploy/update flow → Task 8 + Task 12-13.
- Verification + rollback (tag, revert) → Task 9 Step 2, Task 13.
- Deferred no-auth risk → documented in spec; no task (intentional).
- HomePage no change (layout branch is Phase 1b) → no task, per corrected spec.
