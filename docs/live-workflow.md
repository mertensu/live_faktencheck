# Live Workflow

Step-by-step guide for running a live fact-check session.

For VPS deployment and the always-on backend, see [`docs/deployment.md`](deployment.md).

---

## Before the show

Add the episode to `backend/config.py`:

```python
# In backend/config.py — add a new Episode to the EPISODES dict
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

Open a PR and merge it. The deploy follows automatically within a few minutes — see
[`docs/deployment.md`](deployment.md). Plan for that lag: add the episode well before
the show, not while the guests are being introduced.

---

## During the show

The backend runs permanently on the VPS. Open the session dashboard in Admin-Modus to start recording:

1. Navigate to **https://live-faktencheck.de/maischberger-2026-03-01** and switch to Admin-Modus.
2. Choose your block length (60/120/180s, default 120s) in the recording bar.
3. Click **"Aufnahme starten"** — the browser mic recorder begins capturing audio.
4. Audio blocks are uploaded automatically; click **"Senden"** to flush the current block early, or **"Stop"** to end the recording.

The browser mic captures live speech (in-person conversations or shows playing on speakers) — no virtual audio device needed.

- Review extracted claims at the admin UI (served by the VPS backend at `https://api.live-faktencheck.de`)
- Approve claims → fact-checking runs automatically
- Results appear live at **https://live-faktencheck.de/maischberger-2026-03-01**

---

## Re-run a claim

The production database lives on the server, so claim management happens against the live
backend (the admin UI talks to it directly). A deploy ships code only — it never touches
the database.

To re-run fact-checking on an existing claim (e.g. to overwrite a bad result):

1. Open the live admin UI: **https://live-faktencheck.de/&lt;episode-key&gt;?admin=true**
   (this talks to the VPS backend) → "Gesendete Claims" is pre-populated from the DB
2. Click "Re-send" on the claim → it appears in Pending Claims
3. Approve it → fact-checker runs and overwrites the existing DB record (not a new entry)

The change is live immediately — the frontend reads fact-checks from the API on each poll.

---

## Remove a claim

Through the API — no server access needed. The change appears immediately; the frontend
reads fact-checks on each poll, so no restart and no deploy.

```bash
curl -X DELETE https://api.live-faktencheck.de/api/fact-checks/<ID>
```

The ID is the one shown on the claim in the admin UI.
