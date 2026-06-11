# Browser Microphone Recorder — Design

**Date:** 2026-06-11
**Branch:** `worktree-session-multitenancy`
**Status:** Approved, ready for implementation planning

## Summary

Replace the desktop `listener.py` audio-capture script with an in-browser
microphone recorder. The operator opens a session's live dashboard, clicks
record, and the browser captures microphone audio, chunks it into blocks, and
POSTs each block to the existing `/api/audio-block` endpoint. No backend changes
are required — the endpoint already accepts arbitrary audio bytes plus a
`session_id` form field and an `X-Access-Code` header.

This is the "Browser-Audio-Capture (ersetzt `listener.py`)" step already listed
as Phase 2 in `docs/superpowers/ROADMAP-session-app.md`.

## Motivation

Today, live audio comes from `listener.py`: a Python script run in a terminal
that captures the Mac's *system* audio via the BlackHole virtual device, chunks
it into 120 s WAV blocks, and POSTs them. This requires installing BlackHole,
routing audio, and running a script — a non-trivial setup that also drags in the
`pyaudio`/`pynput` dependencies (and their `portaudio19-dev`/`build-essential`
system build deps, which caused friction during VPS provisioning).

The operator wants zero-setup capture: open the dashboard in a browser, click
record. The chosen capture source is the **microphone** (`getUserMedia`), which
fits in-person conversations (interview / debate / private — the conversation
types generalized in the wizard) and also works for streamed shows played on
speakers. The system-audio (BlackHole) path is intentionally dropped along with
`listener.py`.

## Decisions (locked)

- **Audio source:** microphone via `navigator.mediaDevices.getUserMedia({audio:true})`.
- **Placement:** a persistent recording bar in the **admin area of the
  FactCheckPage** (`/<session_id>`). It must stay mounted while the operator
  reviews claims on the same page — navigating to a separate page would unmount
  and stop the recorder.
- **Block cadence:** configurable in the bar (60 / 120 / 180 s), **default 120 s**,
  matching `listener.py`. Plus a manual flush and a stop.
- **`listener.py`:** **deleted**. The browser mic recorder is the only capture
  path. `pyaudio`/`pynput` dependencies removed.
- **Backend:** **no changes.**

## Architecture

### Capture & chunking — approach A (stop/restart cycles)

`MediaRecorder` timeslice chunks are **not** independently decodable: the
WebM/Opus container header only appears in the first chunk, so later timeslice
blobs can't be transcribed on their own. To produce self-contained blocks:

1. Call `getUserMedia({audio:true})` **once** and keep the resulting
   `MediaStream` warm for the whole session.
2. Start a `MediaRecorder` on that stream.
3. Every `blockSeconds` (and on manual *Senden* / *Stop*): call
   `recorder.stop()`, which fires a single `dataavailable` with the **complete,
   decodable** block; POST it; then immediately `start()` a fresh `MediaRecorder`
   on the same (still-open) stream.

Each block is a self-contained file. Container/codec is whatever the browser
produces (WebM/Opus on Chrome/Firefox, MP4/AAC on Safari); AssemblyAI
auto-detects format from the bytes, so no client-side transcoding is needed. The
~millisecond gap at block boundaries is equivalent to `listener.py`'s existing
block model and is acceptable.

The mic permission is requested once (on first `start`). The stream stays open
across block cycles, so the browser does not re-prompt; `stop()` (the user
action) is the only thing that releases the mic tracks.

### Components

**`frontend/src/hooks/useAudioRecorder.js`** — a testable state-machine hook.

- Internal state: `idle` → `recording` → `idle` (plus `error`).
- Owns the `MediaStream`, the current `MediaRecorder`, the elapsed-time ticker,
  and the auto-send timer.
- Public API:
  - `status` — `'idle' | 'requesting' | 'recording' | 'error'`
  - `elapsed` — seconds in the current block
  - `blocksSent` — count of blocks successfully POSTed this session
  - `error` — user-facing message (permission denied, no mic, send failure)
  - `blockSeconds`, `setBlockSeconds(n)` — current/selectable interval
    (changing it takes effect from the next block; it does not retroactively cut
    the in-progress block)
  - `start()` — request mic (if needed), begin recording + timers
  - `sendNow()` — flush the current block immediately and reset the block timer
  - `stop()` — flush the final block, clear timers, release the mic tracks
- Flush logic is shared by auto-send, `sendNow`, and `stop`: it performs the
  `stop()`→POST→(restart unless stopping) cycle.
- Error handling: `getUserMedia` rejection (NotAllowedError / NotFoundError)
  sets `status='error'` with a German message and does not start. A failed POST
  increments an error indicator but does **not** stop recording (one bad block
  must not kill the session); the block is dropped (no retry queue — out of
  scope).

**`sendAudioBlock(sessionId, blob)` in `frontend/src/services/api.js`** — builds
`FormData` with `audio` (the blob) + `session_id`, attaches `authHeaders()` (the
`X-Access-Code` from localStorage), POSTs to `${BACKEND_URL}/api/audio-block`,
and returns/throws based on the response. Mirrors the existing gated helpers.

**`RecordingBar` component** (e.g. `frontend/src/components/RecordingBar.jsx`)
— the persistent control bar:

- Idle: a **Aufnahme starten** button + block-length selector.
- Recording: `● REC mm:ss` (elapsed), block-length selector, **blocks sent: N**,
  **Senden** (manual flush), **Stop**.
- Error/permission states: clear German messaging (e.g. "Mikrofonzugriff
  verweigert", "Kein Mikrofon gefunden", "Block konnte nicht gesendet werden").
- Styling via `App.css`, consistent with the existing admin UI.

**FactCheckPage integration** — render `<RecordingBar sessionId=… />` in the
admin area, gated by the **existing admin condition** (the same gate that shows
admin controls / send buttons to the owner). Non-admins never see it.

### Data flow

```
RecordingBar (admin)            backend (unchanged)
  └─ useAudioRecorder
       getUserMedia ── once ──▶ MediaStream
       MediaRecorder cycle:
         stop() ─▶ Blob ─▶ sendAudioBlock(sessionId, blob)
                              POST /api/audio-block
                              (multipart audio + session_id,
                               header X-Access-Code)            ─▶ 202 block_id
         start() (fresh recorder, same stream)                     │
                                                                   ▼
                                              transcription → claim extraction
                                                   → pending claims (existing pipeline)
```

## Cleanup (folded in)

Removing `listener.py` cleanly:

- Delete `listener.py`.
- Remove `pyaudio` and `pynput` from `pyproject.toml`; re-lock (`uv lock`). This
  drops the transitive `evdev` and the system build deps
  (`portaudio19-dev`, `build-essential`, `python3-dev`) previously needed on the
  VPS.
- `start_dev.sh`: remove the "Step 4: Start Listener" prompt and the listener
  hints in the closing summary.
- Docs: update `README.md` (audio-capture description + project tree + run
  command), `docs/development-workflow.md`, `docs/deployment.md` (drop the
  build-deps note and `ACCESS_CODE` listener note), `docs/live-workflow.md`
  (BlackHole/listener instructions → browser recorder). Mark the Phase 2 audio
  row done in `docs/superpowers/ROADMAP-session-app.md`.
- The backend doc comment in `backend/app.py` ("Receive audio from listener")
  and the docstring in `backend/routers/audio.py` get a light wording update
  (audio now comes from the browser recorder); behavior unchanged.

## Testing

**vitest unit tests** for `useAudioRecorder` with mocked `MediaRecorder` and
`navigator.mediaDevices.getUserMedia`:

- `start` requests the mic and enters `recording`; permission rejection sets
  `status='error'` and never starts.
- The auto-send cycle fires a flush at the configured interval and immediately
  resumes recording (a fresh recorder is created).
- `sendNow` flushes the current block and resets the elapsed timer.
- `stop` flushes the final block, clears timers, and stops the stream tracks
  (mic released).
- A failed `sendAudioBlock` surfaces an error indicator but recording continues.
- `setBlockSeconds` changes the interval for the next block without cutting the
  current one.

**Manual click-test:** with a real mic, start recording, speak a factual claim,
confirm a block reaches the backend and a claim appears in pending claims;
confirm Stop releases the mic (browser recording indicator clears).

## Out of scope (YAGNI)

- Tab/system-audio capture (`getDisplayMedia`).
- Pause/resume.
- Waveform / level visualization.
- Offline buffering or a send-retry queue.
- Multi-device session sync.

## Risks / notes

- **Browser format variance:** Safari emits MP4/AAC rather than WebM/Opus;
  AssemblyAI handles both. If `MediaRecorder` is unsupported or no
  `mimeType` is acceptable, the bar shows an error and falls back to no capture
  (the operator can still use another browser).
- **Tab backgrounding:** timers may throttle when the tab is fully backgrounded;
  acceptable for an operator actively watching the dashboard. Not engineered
  around in this scope.
- **Single-process backend state** is unchanged; one recorder per session, same
  as one `listener.py` per session today.
