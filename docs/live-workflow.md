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

**Speakers in the live lane:** the live transcript shows AssemblyAI's diarization labels
(`Sprecher A`, `Sprecher B`, …). Click a label and pick the guest to name it; that also
renames every claim already stored under that label. With three guests that is three
clicks. Skip it and claims keep the bare label. Nothing guesses names automatically.

---

## During the show

The backend runs permanently on the VPS. Open the session page with your access code
unlocked:

1. Navigate to **https://live-faktencheck.de/maischberger-2026-03-01**. The short guide
   (Kurzanleitung) opens first; close it or reopen it from the header at any time.
2. Pick the microphone ("Mikrofone laden" reveals the device names) and copy the share link
   for viewers if needed.
3. Click **◉ Live-Check** in the header. The browser streams the mic to the backend; the
   live transcript appears within a second or two.
4. Assign speakers by clicking a label (`Sprecher A`, …) and picking the guest.
5. Claims are gated and checked automatically — there is no approval step. Each checked
   claim is marked in the transcript; click it for the verdict, reasoning and sources.
6. **Live stoppen** ends the stream. Viewers on the share link see the results stream.

The browser mic captures live speech (in-person conversations or shows playing on
speakers) — no virtual audio device needed. Streaming time counts against the access
code's live-audio budget (see [`docs/deployment.md`](deployment.md#live-audio-limit-phase-3b)).

---

## A result is wrong

There is no re-run: the live lane checks each claim once, while it is on air. If a result
is wrong or misleading, remove it (below). Speaker names can still be corrected during the
session by reassigning the label.

---

## Remove a claim

Through the API — no server access needed. The change appears immediately; the frontend
reads fact-checks on each poll, so no restart and no deploy.

```bash
# find the ID
curl -s "https://api.live-faktencheck.de/api/fact-checks?session_id=<episode-key>"

# delete it (gated: needs an access code)
curl -X DELETE -H "X-Access-Code: <code>" https://api.live-faktencheck.de/api/fact-checks/<ID>
```
