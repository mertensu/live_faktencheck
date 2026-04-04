# Live Workflow

Step-by-step guide for running a live fact-check session.

---

## Before the show

**Step 1 — you do:** Add the episode to `config.py` (without `publish=True`):

```python
# In config.py — add a new Episode to the EPISODES dict
EPISODES = {
    "maischberger-2026-03-01": Episode(
        key="maischberger-2026-03-01",
        show="maischberger",
        date="1. März 2026",
        guests=[
            "Sandra Maischberger (Moderatorin)",
            "Guest A (Partei)",
            "Guest B (Partei)",
        ],
    ),
    # ... existing episodes
}
```

**Step 2 — the script does the rest:** sets `publish=True`, creates the empty episode JSON, updates `shows.json`, commits and pushes (Cloudflare deploys automatically):

```bash
./publish_episode.sh maischberger-2026-03-01
```

---

## During the show

Start backend + Cloudflare Tunnel, then respond to the listener prompt:

```bash
# Terminal 1: start backend, tunnel, local admin UI — then prompts for listener
./start_production.sh maischberger-2026-03-01
# → answer 'y' to start listener in same terminal
```

- Route your audio through BlackHole into the listener
- Review extracted claims at **http://localhost:3000** (Admin UI, local only)
- Approve claims → fact-checking runs automatically
- Results appear live at **https://live-faktencheck.de/maischberger-2026-03-01**

---

## After the show

Export results as static files so the page stays online without a running backend:

```bash
./stop_production.sh --permanent
```

This exports the SQLite data to `frontend/public/data/<episode>.json`, commits, pushes, and waits for Cloudflare to build before shutting down the tunnel. No downtime.

---

## Re-run a claim

To re-run fact-checking on an existing claim (e.g. to overwrite a bad result):

1. Start the dev server: `./start_dev.sh <episode-key>`
2. Open admin UI at **http://localhost:3000** → "Gesendete Claims" is pre-populated from the DB
3. Click "Re-send" on the claim → it appears in Pending Claims
4. Approve it → fact-checker runs and overwrites the existing DB record (not a new entry)
5. Re-export: `uv run python export_episode.py --json <episode-key>`
6. Commit and push

---

## Remove a claim

```bash
./manage_claim.sh <episode-key>          # lists claims and prompts for ID
# or directly:
./manage_claim.sh <episode-key> delete <id>
```

Requires the backend to be running (`./start_dev.sh <episode-key>`). After deletion the script re-exports the episode JSON automatically. Then commit and push.

**Fallback (no backend running):**
```bash
uv run python -c "import sqlite3; conn = sqlite3.connect('backend/data/factcheck.db'); conn.execute('DELETE FROM fact_checks WHERE id = <ID>'); conn.commit(); conn.close()"
uv run python export_episode.py --json <episode-key>
```
