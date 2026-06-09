# Live Workflow

Step-by-step guide for running a live fact-check session.

For VPS deployment and the always-on backend, see [`docs/deployment.md`](deployment.md).

---

## Before the show

Add the episode to `config.py`:

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

Commit and push — the VPS backend picks up the new episode on the next deploy (`./deploy/deploy.sh`).

---

## During the show

The backend runs permanently on the VPS. Start the listener locally:

```bash
uv run python listener.py maischberger-2026-03-01
```

- Route your audio through BlackHole into the listener
- Review extracted claims at the admin UI (served by the VPS backend at `https://api.live-faktencheck.de`)
- Approve claims → fact-checking runs automatically
- Results appear live at **https://live-faktencheck.de/maischberger-2026-03-01**

---

## Re-run a claim

To re-run fact-checking on an existing claim (e.g. to overwrite a bad result):

1. Start the dev server locally: `./start_dev.sh <episode-key>`
2. Open admin UI at **http://localhost:3000** → "Gesendete Claims" is pre-populated from the DB
3. Click "Re-send" on the claim → it appears in Pending Claims
4. Approve it → fact-checker runs and overwrites the existing DB record (not a new entry)
5. Commit and push; run `./deploy/deploy.sh` to deploy

---

## Remove a claim

```bash
uv run python -c "import sqlite3; conn = sqlite3.connect('backend/data/factcheck.db'); conn.execute('DELETE FROM fact_checks WHERE id = <ID>'); conn.commit(); conn.close()"
```

Then deploy: `./deploy/deploy.sh`
