# Browser Microphone Recorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the desktop `listener.py` audio-capture script with an in-browser microphone recorder that chunks mic audio into self-contained blocks and POSTs them to the existing `/api/audio-block` endpoint.

**Architecture:** A testable React hook (`useAudioRecorder`) owns a single warm `MediaStream` and runs a stop→POST→restart `MediaRecorder` cycle to produce independently-decodable blocks. A `sendAudioBlock` API helper mirrors the existing gated `fetch` helpers (`X-Access-Code` header). A `RecordingBar` component renders the controls in the FactCheckPage admin area, gated by the existing `isAdminMode` condition. The backend is unchanged. `listener.py` and its `pyaudio`/`pynput` deps are deleted, and the docs/scripts that referenced it are updated.

**Tech Stack:** React 18 (hooks), Vite, Vitest 4 (with jsdom + `@testing-library/react` for hook tests), browser `MediaRecorder` / `getUserMedia` APIs. Backend: FastAPI (unchanged). Packaging: `uv` / `pyproject.toml`.

---

## Background for the implementing engineer

This is a React + FastAPI app. The frontend lives in `frontend/`, uses **`bun`** (never `npm`), and is tested with **vitest** (`cd frontend && bun run test`). The backend is Python managed with **`uv`** (never `pip`).

Key facts you need:

- **The backend endpoint already exists and needs NO changes.** `POST /api/audio-block` (`backend/routers/audio.py:48`) accepts multipart form data: `audio` (`UploadFile`), `session_id` (`Form`), and an `X-Access-Code` header (via `require_code` dependency). It returns `202` with `{status, message, block_id}`. AssemblyAI auto-detects the audio container from the bytes, so WebM/Opus (Chrome/Firefox) and MP4/AAC (Safari) both work — no client-side transcoding.
- **The session id is the `episodeKey` prop** in `FactCheckPage` (`frontend/src/pages/FactCheckPage.jsx:30`). Pass it to the recorder as `sessionId`.
- **The admin gate** is the `isAdminMode` boolean in `FactCheckPage`. The admin UI is rendered inside the `{isAdminMode ? (...) : (...)}` block at `frontend/src/pages/FactCheckPage.jsx:657`. The RecordingBar goes at the top of the admin branch.
- **API helper pattern:** see `frontend/src/services/api.js`. `authHeaders()` returns `FETCH_HEADERS` plus `X-Access-Code` when a code is stored. Note: `authHeaders()` sets `Content-Type: application/json` — for multipart `FormData` we must NOT send a `Content-Type` header (the browser sets the multipart boundary itself), so `sendAudioBlock` builds its own header object using only the access code.
- **Existing frontend test:** `frontend/src/wizard/wizardLogic.test.js` shows the vitest style (`import { describe, it, expect } from 'vitest'`). That test is pure logic. Our hook tests need a DOM + React renderer, which Task 1 sets up.

### File Structure

| File | Responsibility |
|------|----------------|
| `frontend/vitest.config.js` (create) | Configure vitest `environment: 'jsdom'` so hook tests can run. |
| `frontend/src/hooks/useAudioRecorder.js` (create) | State-machine hook: owns stream, recorder, timers; exposes status/elapsed/blocksSent/error/blockSeconds + start/sendNow/stop/setBlockSeconds. |
| `frontend/src/hooks/useAudioRecorder.test.js` (create) | Vitest unit tests with mocked `MediaRecorder` + `getUserMedia`. |
| `frontend/src/services/api.js` (modify) | Add `sendAudioBlock(sessionId, blob)`. |
| `frontend/src/services/api.test.js` (create) | Test `sendAudioBlock` builds correct FormData/headers and handles errors. |
| `frontend/src/components/RecordingBar.jsx` (create) | Presentational control bar wired to the hook. |
| `frontend/src/App.css` (modify) | `.recording-bar` styles consistent with admin UI. |
| `frontend/src/pages/FactCheckPage.jsx` (modify) | Render `<RecordingBar sessionId={episodeKey} />` in the admin branch. |
| `listener.py` (delete) | Removed; browser recorder replaces it. |
| `pyproject.toml` (modify) | Remove `pyaudio`, `pynput`; re-lock. |
| `start_dev.sh` (modify) | Drop the "Start Listener" step + hints. |
| `backend/app.py`, `backend/routers/audio.py` (modify) | Light wording update in comments/docstring. |
| Docs (modify) | `README.md`, `docs/development-workflow.md`, `docs/deployment.md`, `docs/live-workflow.md`, `docs/superpowers/ROADMAP-session-app.md`. |

---

## Task 1: Set up jsdom test environment

The hook uses `useState`/`useRef`/`useEffect`, so its tests need a DOM and React's `renderHook`. Vitest currently defaults to the `node` environment with no DOM. This task adds jsdom + `@testing-library/react` and a vitest config, verified by a throwaway smoke test.

**Files:**
- Create: `frontend/vitest.config.js`
- Create (temporary): `frontend/src/hooks/_smoke.test.js`

- [ ] **Step 1: Install dev dependencies**

```bash
cd frontend && bun add -d jsdom @testing-library/react @testing-library/dom
```

Expected: `package.json` `devDependencies` now lists `jsdom`, `@testing-library/react`, `@testing-library/dom`.

- [ ] **Step 2: Create the vitest config selecting jsdom**

Create `frontend/vitest.config.js`:

```js
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: false,
  },
})
```

- [ ] **Step 3: Write a smoke test that proves jsdom + renderHook work**

Create `frontend/src/hooks/_smoke.test.js`:

```js
import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useState } from 'react'

describe('jsdom + renderHook smoke', () => {
  it('has a document and can render a hook', () => {
    expect(typeof document).toBe('object')
    const { result } = renderHook(() => useState(0))
    act(() => result.current[1](5))
    expect(result.current[0]).toBe(5)
  })
})
```

- [ ] **Step 4: Run the smoke test**

Run: `cd frontend && bun run test src/hooks/_smoke.test.js`
Expected: PASS (1 test). If it errors with "document is not defined", the vitest config is not being picked up.

- [ ] **Step 5: Confirm the existing suite still passes**

Run: `cd frontend && bun run test`
Expected: PASS — including `wizardLogic.test.js`.

- [ ] **Step 6: Delete the smoke test and commit**

```bash
rm frontend/src/hooks/_smoke.test.js
git add frontend/package.json frontend/bun.lock frontend/vitest.config.js
git commit -m "test: add jsdom + testing-library for hook tests"
```

---

## Task 2: `sendAudioBlock` API helper

A thin POST helper that uploads one audio blob as multipart form data with the access-code header. It does NOT use `authHeaders()` because that forces `Content-Type: application/json`; for `FormData` the browser must set the multipart boundary itself.

**Files:**
- Modify: `frontend/src/services/api.js`
- Test: `frontend/src/services/api.test.js` (create)

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/services/api.test.js`:

```js
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { sendAudioBlock } from './api'

describe('sendAudioBlock', () => {
  beforeEach(() => {
    localStorage.clear()
    global.fetch = vi.fn()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('POSTs multipart form data with audio + session_id and no JSON content-type', async () => {
    localStorage.setItem('fc_access_code', 'SECRET')
    global.fetch.mockResolvedValue({
      ok: true,
      headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ block_id: 'block_1' }),
      url: '', status: 202,
    })
    const blob = new Blob(['xx'], { type: 'audio/webm' })

    const result = await sendAudioBlock('sess-42', blob)

    expect(global.fetch).toHaveBeenCalledTimes(1)
    const [url, opts] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/audio-block$/)
    expect(opts.method).toBe('POST')
    expect(opts.headers['X-Access-Code']).toBe('SECRET')
    expect(opts.headers['Content-Type']).toBeUndefined()
    expect(opts.body).toBeInstanceOf(FormData)
    expect(opts.body.get('session_id')).toBe('sess-42')
    expect(opts.body.get('audio')).toBeInstanceOf(Blob)
    expect(result).toEqual({ block_id: 'block_1' })
  })

  it('throws on a non-ok response', async () => {
    global.fetch.mockResolvedValue({
      ok: false,
      headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ detail: 'nope' }),
      url: '', status: 403,
    })
    const blob = new Blob(['xx'], { type: 'audio/webm' })
    await expect(sendAudioBlock('s', blob)).rejects.toThrow('nope')
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && bun run test src/services/api.test.js`
Expected: FAIL with `sendAudioBlock is not a function` (or import error).

- [ ] **Step 3: Implement `sendAudioBlock`**

In `frontend/src/services/api.js`, add at the end of the file:

```js
// Upload one recorded audio block to the existing /api/audio-block endpoint.
// Uses FormData, so we must NOT set Content-Type (the browser sets the
// multipart boundary). Only the access-code header is attached manually.
export async function sendAudioBlock(sessionId, blob) {
  const form = new FormData()
  form.append('audio', blob, 'block.webm')
  form.append('session_id', sessionId)

  const code = getAccessCode()
  const headers = code ? { 'X-Access-Code': code } : {}

  const res = await fetch(`${BACKEND_URL}/api/audio-block`, {
    method: 'POST', headers, body: form,
  })
  const data = await safeJsonParse(res, 'sendAudioBlock')
  if (!res.ok) {
    throw new Error(data?.detail || `sendAudioBlock failed (${res.status})`)
  }
  return data  // { status, message, block_id }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && bun run test src/services/api.test.js`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/api.js frontend/src/services/api.test.js
git commit -m "feat: add sendAudioBlock API helper"
```

---

## Task 3: `useAudioRecorder` hook — start / error / stop

Build the state-machine hook incrementally. This task covers requesting the mic, entering `recording`, permission-rejection handling, and `stop()` (flush + release tracks). The auto-send timer and `sendNow` come in Task 4. Tests mock `MediaRecorder` and `navigator.mediaDevices.getUserMedia`.

**Files:**
- Create: `frontend/src/hooks/useAudioRecorder.js`
- Test: `frontend/src/hooks/useAudioRecorder.test.js`

**Mock contract (used by all hook tests):** A fake `MediaRecorder` whose `.stop()` synchronously fires `ondataavailable` with a non-empty `Blob`, then fires `onstop`. A fake `getUserMedia` resolving to a stream with one stoppable track.

- [ ] **Step 1: Write the failing tests for start / error / stop**

Create `frontend/src/hooks/useAudioRecorder.test.js`:

```js
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useAudioRecorder } from './useAudioRecorder'
import * as api from '../services/api'

// --- MediaRecorder / getUserMedia mocks ---
let recorders = []   // every MediaRecorder constructed during a test
let tracks = []      // every track in the granted stream

class FakeMediaRecorder {
  constructor(stream) {
    this.stream = stream
    this.state = 'inactive'
    this.ondataavailable = null
    this.onstop = null
    recorders.push(this)
  }
  start() { this.state = 'recording' }
  stop() {
    this.state = 'inactive'
    // fire a complete, decodable block then onstop (synchronous for test determinism)
    if (this.ondataavailable) {
      this.ondataavailable({ data: new Blob(['audio'], { type: 'audio/webm' }) })
    }
    if (this.onstop) this.onstop()
  }
}

function installMediaMocks({ deny = false } = {}) {
  recorders = []
  tracks = [{ stop: vi.fn() }]
  const stream = { getTracks: () => tracks }
  global.MediaRecorder = FakeMediaRecorder
  global.navigator.mediaDevices = {
    getUserMedia: vi.fn(() =>
      deny
        ? Promise.reject(Object.assign(new Error('denied'), { name: 'NotAllowedError' }))
        : Promise.resolve(stream)
    ),
  }
}

describe('useAudioRecorder: start / error / stop', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    installMediaMocks()
    vi.spyOn(api, 'sendAudioBlock').mockResolvedValue({ block_id: 'b1' })
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('start() requests the mic and enters recording', async () => {
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    expect(result.current.status).toBe('idle')

    await act(async () => { await result.current.start() })

    expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledWith({ audio: true })
    expect(result.current.status).toBe('recording')
    expect(recorders).toHaveLength(1)
    expect(recorders[0].state).toBe('recording')
  })

  it('permission rejection sets status=error and never starts a recorder', async () => {
    installMediaMocks({ deny: true })
    const { result } = renderHook(() => useAudioRecorder('sess-1'))

    await act(async () => { await result.current.start() })

    expect(result.current.status).toBe('error')
    expect(result.current.error).toMatch(/Mikrofonzugriff verweigert/)
    expect(recorders).toHaveLength(0)
  })

  it('stop() flushes the final block, releases tracks, returns to idle', async () => {
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    await act(async () => { await result.current.start() })

    await act(async () => { await result.current.stop() })

    expect(api.sendAudioBlock).toHaveBeenCalledTimes(1)         // final block sent
    expect(api.sendAudioBlock).toHaveBeenCalledWith('sess-1', expect.any(Blob))
    expect(tracks[0].stop).toHaveBeenCalled()                   // mic released
    expect(result.current.status).toBe('idle')
    expect(result.current.blocksSent).toBe(1)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && bun run test src/hooks/useAudioRecorder.test.js`
Expected: FAIL with `useAudioRecorder is not a function` / import error.

- [ ] **Step 3: Implement the hook (start / error / stop; flush scaffolding)**

Create `frontend/src/hooks/useAudioRecorder.js`:

```js
import { useState, useRef, useCallback, useEffect } from 'react'
import { sendAudioBlock } from '../services/api'

const DEFAULT_BLOCK_SECONDS = 120

// German user-facing messages.
const MSG = {
  denied: 'Mikrofonzugriff verweigert',
  noMic: 'Kein Mikrofon gefunden',
  sendFailed: 'Block konnte nicht gesendet werden',
  unsupported: 'Audioaufnahme wird von diesem Browser nicht unterstützt',
}

export function useAudioRecorder(sessionId) {
  const [status, setStatus] = useState('idle')      // idle | requesting | recording | error
  const [elapsed, setElapsed] = useState(0)
  const [blocksSent, setBlocksSent] = useState(0)
  const [error, setError] = useState(null)
  const [blockSeconds, setBlockSecondsState] = useState(DEFAULT_BLOCK_SECONDS)

  const streamRef = useRef(null)
  const recorderRef = useRef(null)
  const tickRef = useRef(null)            // elapsed-time interval
  const autoSendRef = useRef(null)        // auto-send interval
  const stoppingRef = useRef(false)       // true while stop() is releasing the mic
  const blockSecondsRef = useRef(DEFAULT_BLOCK_SECONDS)

  // Block length is locked once recording starts (only honored while idle).
  const setBlockSeconds = useCallback((n) => {
    setStatus((s) => {
      if (s === 'idle') {
        blockSecondsRef.current = n
        setBlockSecondsState(n)
      }
      return s
    })
  }, [])

  const clearTimers = useCallback(() => {
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null }
    if (autoSendRef.current) { clearInterval(autoSendRef.current); autoSendRef.current = null }
  }, [])

  // Start a fresh MediaRecorder on the (still-open) stream.
  const startRecorder = useCallback(() => {
    const rec = new MediaRecorder(streamRef.current)
    recorderRef.current = rec
    rec.start()
  }, [])

  // Core cycle: stop current recorder (-> one complete block), POST it, then
  // restart a fresh recorder unless we are stopping. Shared by auto-send,
  // sendNow, and stop.
  const flush = useCallback(async () => {
    const rec = recorderRef.current
    if (!rec || rec.state !== 'recording') return

    const blob = await new Promise((resolve) => {
      rec.ondataavailable = (e) => resolve(e.data)
      rec.stop()
    })

    if (!stoppingRef.current) startRecorder()   // resume immediately
    setElapsed(0)

    try {
      await sendAudioBlock(sessionId, blob)
      setBlocksSent((n) => n + 1)
    } catch {
      // One bad block must not kill the session: surface, keep recording.
      setError(MSG.sendFailed)
    }
  }, [sessionId, startRecorder])

  const start = useCallback(async () => {
    if (typeof MediaRecorder === 'undefined') {
      setStatus('error'); setError(MSG.unsupported); return
    }
    setStatus('requesting'); setError(null)
    try {
      streamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      setStatus('error')
      setError(e && e.name === 'NotFoundError' ? MSG.noMic : MSG.denied)
      return
    }
    stoppingRef.current = false
    startRecorder()
    setElapsed(0)
    tickRef.current = setInterval(() => setElapsed((s) => s + 1), 1000)
    autoSendRef.current = setInterval(() => { flush() }, blockSecondsRef.current * 1000)
    setStatus('recording')
  }, [flush, startRecorder])

  const sendNow = useCallback(async () => {
    await flush()
  }, [flush])

  const stop = useCallback(async () => {
    stoppingRef.current = true
    clearTimers()
    await flush()                       // final block, no restart
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
    recorderRef.current = null
    setElapsed(0)
    setStatus('idle')
  }, [flush, clearTimers])

  // Release the mic if the component unmounts mid-recording.
  useEffect(() => () => {
    clearTimers()
    if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop())
  }, [clearTimers])

  return {
    status, elapsed, blocksSent, error,
    blockSeconds, setBlockSeconds,
    start, sendNow, stop,
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && bun run test src/hooks/useAudioRecorder.test.js`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useAudioRecorder.js frontend/src/hooks/useAudioRecorder.test.js
git commit -m "feat: useAudioRecorder hook (start/stop/error)"
```

---

## Task 4: `useAudioRecorder` — auto-send, sendNow, failed-send, locked interval

Add the remaining tests against the hook already built in Task 3. The implementation already covers these behaviors; this task proves them and fixes the hook if any test fails. Append these `describe` blocks to `useAudioRecorder.test.js` (reuse the `FakeMediaRecorder` / `installMediaMocks` helpers — keep them at module scope so both describe blocks share them).

**Files:**
- Modify: `frontend/src/hooks/useAudioRecorder.test.js`
- Modify (only if a test fails): `frontend/src/hooks/useAudioRecorder.js`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/hooks/useAudioRecorder.test.js`:

```js
describe('useAudioRecorder: auto-send / sendNow / failures / lock', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    installMediaMocks()
    vi.spyOn(api, 'sendAudioBlock').mockResolvedValue({ block_id: 'b1' })
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('auto-send fires a flush at the configured interval and resumes recording', async () => {
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    act(() => { result.current.setBlockSeconds(60) })
    await act(async () => { await result.current.start() })
    expect(recorders).toHaveLength(1)

    // advance one interval (60s)
    await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })

    expect(api.sendAudioBlock).toHaveBeenCalledTimes(1)
    expect(recorders).toHaveLength(2)               // a fresh recorder was created
    expect(recorders[1].state).toBe('recording')
    expect(result.current.status).toBe('recording')
  })

  it('sendNow flushes the current block and resets elapsed', async () => {
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    await act(async () => { await result.current.start() })
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
    expect(result.current.elapsed).toBe(5)

    await act(async () => { await result.current.sendNow() })

    expect(api.sendAudioBlock).toHaveBeenCalledTimes(1)
    expect(result.current.elapsed).toBe(0)
    expect(result.current.blocksSent).toBe(1)
    expect(result.current.status).toBe('recording')   // still recording
  })

  it('a failed send surfaces an error but keeps recording', async () => {
    api.sendAudioBlock.mockRejectedValueOnce(new Error('boom'))
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    await act(async () => { await result.current.start() })

    await act(async () => { await result.current.sendNow() })

    expect(result.current.error).toMatch(/Block konnte nicht gesendet werden/)
    expect(result.current.status).toBe('recording')
    expect(result.current.blocksSent).toBe(0)
  })

  it('setBlockSeconds is honored while idle but ignored while recording', async () => {
    const { result } = renderHook(() => useAudioRecorder('sess-1'))
    act(() => { result.current.setBlockSeconds(180) })
    expect(result.current.blockSeconds).toBe(180)

    await act(async () => { await result.current.start() })
    act(() => { result.current.setBlockSeconds(60) })   // ignored while recording
    expect(result.current.blockSeconds).toBe(180)
  })
})
```

- [ ] **Step 2: Run the tests**

Run: `cd frontend && bun run test src/hooks/useAudioRecorder.test.js`
Expected: PASS (7 tests total). If any FAIL, debug the hook with superpowers:systematic-debugging — likely culprits: the auto-send interval reading a stale `blockSecondsRef`, or `sendNow` not resetting `elapsed`. Fix `useAudioRecorder.js`, re-run.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useAudioRecorder.test.js frontend/src/hooks/useAudioRecorder.js
git commit -m "test: cover auto-send, sendNow, send-failure, interval lock"
```

---

## Task 5: `RecordingBar` component

Presentational control bar wired to `useAudioRecorder`. Idle shows a start button + block-length selector (editable). Recording shows `● REC mm:ss`, the selector disabled/locked, blocks-sent count, Senden, and Stop. Errors render in German. This is a presentational component; verify it by reading the code and running the build (rendering tests are out of scope per the spec, which only requires hook + API tests).

**Files:**
- Create: `frontend/src/components/RecordingBar.jsx`
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/RecordingBar.jsx`:

```jsx
import { useAudioRecorder } from '../hooks/useAudioRecorder'

const BLOCK_OPTIONS = [60, 120, 180]

function formatElapsed(totalSeconds) {
  const m = String(Math.floor(totalSeconds / 60)).padStart(2, '0')
  const s = String(totalSeconds % 60).padStart(2, '0')
  return `${m}:${s}`
}

export function RecordingBar({ sessionId }) {
  const {
    status, elapsed, blocksSent, error,
    blockSeconds, setBlockSeconds, start, sendNow, stop,
  } = useAudioRecorder(sessionId)

  const isRecording = status === 'recording'
  const isRequesting = status === 'requesting'

  return (
    <div className="recording-bar">
      {isRecording ? (
        <>
          <span className="recording-bar-rec">● REC {formatElapsed(elapsed)}</span>
          <label className="recording-bar-interval">
            Blocklänge:
            <select value={blockSeconds} disabled>
              {BLOCK_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}s</option>
              ))}
            </select>
          </label>
          <span className="recording-bar-count">Blöcke gesendet: {blocksSent}</span>
          <button className="recording-bar-send" onClick={() => sendNow()}>Senden</button>
          <button className="recording-bar-stop" onClick={() => stop()}>Stop</button>
        </>
      ) : (
        <>
          <label className="recording-bar-interval">
            Blocklänge:
            <select
              value={blockSeconds}
              onChange={(e) => setBlockSeconds(Number(e.target.value))}
              disabled={isRequesting}
            >
              {BLOCK_OPTIONS.map((n) => (
                <option key={n} value={n}>{n}s</option>
              ))}
            </select>
          </label>
          <button
            className="recording-bar-start"
            onClick={() => start()}
            disabled={isRequesting}
          >
            {isRequesting ? 'Mikrofon…' : 'Aufnahme starten'}
          </button>
        </>
      )}
      {error && <span className="recording-bar-error">{error}</span>}
    </div>
  )
}
```

- [ ] **Step 2: Add styles to `App.css`**

Append to `frontend/src/App.css` (match the existing admin look — neutral panel, the `.admin-toggle` button styling around line 793 is a good reference for buttons):

```css
.recording-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
  flex-wrap: wrap;
  padding: 0.75rem 1rem;
  margin-bottom: 1rem;
  background: #1e1e24;
  border: 1px solid #33333d;
  border-radius: 8px;
}

.recording-bar-rec {
  font-weight: 700;
  color: #e23b3b;
  font-variant-numeric: tabular-nums;
}

.recording-bar-interval {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  color: #cfcfd6;
}

.recording-bar-count {
  color: #9a9aa3;
  font-variant-numeric: tabular-nums;
}

.recording-bar button {
  padding: 0.4rem 0.9rem;
  border-radius: 6px;
  border: 1px solid #44444f;
  background: #2a2a33;
  color: #f0f0f3;
  cursor: pointer;
}

.recording-bar button:hover { background: #34343f; }
.recording-bar button:disabled { opacity: 0.5; cursor: default; }

.recording-bar-start { border-color: #2e7d32; }
.recording-bar-stop { border-color: #b53b3b; }

.recording-bar-error {
  color: #e88; 
  font-weight: 600;
}
```

- [ ] **Step 3: Verify the build compiles**

Run: `cd frontend && bun run build`
Expected: build succeeds (Vite emits `dist/`). This catches JSX/import errors in the new component.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/RecordingBar.jsx frontend/src/App.css
git commit -m "feat: RecordingBar control component"
```

---

## Task 6: Wire RecordingBar into the FactCheckPage admin area

Render the bar at the top of the admin branch so it stays mounted while the operator reviews claims. Non-admins (the `else` branch) never see it.

**Files:**
- Modify: `frontend/src/pages/FactCheckPage.jsx`

- [ ] **Step 1: Add the import**

Near the other component imports at the top of `frontend/src/pages/FactCheckPage.jsx`, add:

```jsx
import { RecordingBar } from '../components/RecordingBar'
```

- [ ] **Step 2: Render the bar inside the admin branch**

In `frontend/src/pages/FactCheckPage.jsx`, the admin branch currently begins (around line 657):

```jsx
        {isAdminMode ? (
          <AdminView
```

Change it to wrap the admin content and mount the bar above `AdminView`:

```jsx
        {isAdminMode ? (
          <>
            <RecordingBar sessionId={episodeKey} />
            <AdminView
```

Then close the new fragment after the existing `AdminView` closing tag (`/>`):

```jsx
              onRetrigger={retriggerBlock}
            />
          </>
        ) : (
```

(Only the wrapping `<>…</>` and the `<RecordingBar … />` line are new; the `AdminView` props are unchanged.)

- [ ] **Step 3: Verify the build compiles**

Run: `cd frontend && bun run build`
Expected: build succeeds. A mismatched fragment tag fails here.

- [ ] **Step 4: Run the full frontend test suite**

Run: `cd frontend && bun run test`
Expected: PASS — wizard, api, and useAudioRecorder tests all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/FactCheckPage.jsx
git commit -m "feat: mount RecordingBar in FactCheckPage admin area"
```

---

## Task 7: Delete `listener.py` and remove its Python deps

`listener.py` is the only consumer of `pyaudio`/`pynput`. Removing it lets us drop those deps and their system build requirements.

**Files:**
- Delete: `listener.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock` (regenerated)

- [ ] **Step 1: Confirm nothing else imports the dropped packages**

Run: `grep -rn "import pyaudio\|from pyaudio\|import pynput\|from pynput\|listener" --include=*.py backend/ config.py 2>/dev/null`
Expected: no matches outside `listener.py` itself. If anything else imports them, STOP and report — the spec assumes `listener.py` is the sole consumer.

- [ ] **Step 2: Delete the script**

```bash
git rm listener.py
```

- [ ] **Step 3: Remove the dependencies from `pyproject.toml`**

In `pyproject.toml`, delete the `"pyaudio>=0.2.14",` line (line 9) and the `"pynput>=1.8.1",` line (line 13) from the dependencies array.

- [ ] **Step 4: Re-lock**

Run: `uv lock`
Expected: lockfile updates; `pyaudio`, `pynput`, and transitive `evdev` are removed.

- [ ] **Step 5: Verify the environment still resolves and backend tests pass**

Run: `uv sync && uv run pytest backend/tests -m "not integration"`
Expected: sync succeeds; unit tests PASS (the backend never imported listener).

- [ ] **Step 6: Commit**

```bash
git add listener.py pyproject.toml uv.lock
git commit -m "chore: remove listener.py and pyaudio/pynput deps"
```

---

## Task 8: Update `start_dev.sh`

Drop the listener step and its hints now that capture is in-browser.

**Files:**
- Modify: `start_dev.sh`

- [ ] **Step 1: Remove the listener hint in the summary**

In `start_dev.sh`, delete the line (around line 150):

```sh
echo -e "   2. Start Listener: ${YELLOW}uv run python listener.py $EPISODE_KEY${NC}"
```

If the surrounding numbered list now has a gap (e.g. a following "3."), renumber the remaining items so they read sequentially.

- [ ] **Step 2: Remove the "Step 4: Start Listener" block**

Delete the entire block (around lines 155–164):

```sh
# Step 4: Start Listener?
print_header "Step 4: Start Listener"
printf "${BLUE}Start audio listener now? [y/N] ${NC}"
read -r START_LISTENER
if [[ "$START_LISTENER" =~ ^[Yy]$ ]]; then
    ...
    exec uv run python listener.py "$EPISODE_KEY"
else
    print_info "Run when ready: uv run python listener.py $EPISODE_KEY"
fi
```

(Read the file first to capture the exact block boundaries before deleting; remove the whole `Step 4` section including its `print_header`.)

- [ ] **Step 3: Verify the script still parses**

Run: `bash -n start_dev.sh`
Expected: no output (syntax OK).

- [ ] **Step 4: Confirm no listener references remain**

Run: `grep -n -i "listener\|blackhole" start_dev.sh`
Expected: no matches.

- [ ] **Step 5: Commit**

```bash
git add start_dev.sh
git commit -m "chore: drop listener step from start_dev.sh"
```

---

## Task 9: Update backend comments and docs

Behavior is unchanged; only wording referencing `listener.py`/BlackHole is updated to mention the browser recorder, and the ROADMAP row is marked done.

**Files:**
- Modify: `backend/app.py`, `backend/routers/audio.py`
- Modify: `README.md`, `docs/development-workflow.md`, `docs/deployment.md`, `docs/live-workflow.md`, `docs/superpowers/ROADMAP-session-app.md`

- [ ] **Step 1: Update the backend comment in `backend/app.py`**

Change line 158 from:

```
|    POST /api/audio-block     - Receive audio from listener   |
```

to:

```
|    POST /api/audio-block     - Receive audio from browser    |
```

(Keep the box-drawing alignment — pad/truncate so the trailing `|` stays in the same column.)

- [ ] **Step 2: Update the docstring in `backend/routers/audio.py`**

Change the docstring at line 55–56 from:

```python
    Receive audio block from listener.py and start processing pipeline.
```

to:

```python
    Receive audio block from the browser mic recorder and start the pipeline.
```

- [ ] **Step 3: Update the docs**

For each of `README.md`, `docs/development-workflow.md`, `docs/deployment.md`, `docs/live-workflow.md`:

```bash
grep -rn -i "listener\|blackhole\|pyaudio\|pynput\|portaudio\|build-essential" README.md docs/development-workflow.md docs/deployment.md docs/live-workflow.md
```

For each hit, replace the listener/BlackHole capture instructions with the browser-recorder workflow: "Open the session dashboard in admin mode and click **Aufnahme starten** in the recording bar." Specifically:
- `README.md`: audio-capture description, the project tree entry for `listener.py` (remove it), and any `uv run python listener.py` run command.
- `docs/development-workflow.md`: replace the listener run step.
- `docs/deployment.md`: drop the `portaudio19-dev`/`build-essential`/`python3-dev` build-deps note and the `ACCESS_CODE` listener note.
- `docs/live-workflow.md`: replace BlackHole/listener setup with the browser recorder steps.

- [ ] **Step 4: Mark the Phase 2 audio row done in the ROADMAP**

In `docs/superpowers/ROADMAP-session-app.md`, find the Phase 2 "Browser-Audio-Capture (ersetzt `listener.py`)" row and mark it done (match the existing done-marker style used by other completed rows — check the file for whether that's `[x]`, ✅, or a status column).

- [ ] **Step 5: Verify no stale references remain**

Run: `grep -rn -i "listener.py\|blackhole" README.md docs/ backend/ | grep -v "ROADMAP\|plans/\|specs/"`
Expected: no matches (historical mentions inside `docs/superpowers/plans/` and `specs/` are fine to leave).

- [ ] **Step 6: Commit**

```bash
git add backend/app.py backend/routers/audio.py README.md docs/
git commit -m "docs: replace listener references with browser recorder"
```

---

## Task 10: Manual click-test (human verification)

Automated tests cover the hook and API. This task is the real-mic smoke test from the spec. It requires a human with a microphone and is not automatable.

- [ ] **Step 1: Start the app**

Run: `./start_dev.sh <session-key>` (or `./backend/run.sh` + `cd frontend && bun run dev` in two terminals). Create/open a session and enter its dashboard.

- [ ] **Step 2: Enter admin mode and start recording**

Open the session at `/<session_id>`, switch to **Admin-Modus**, confirm the recording bar is visible. Pick a block length, click **Aufnahme starten**, and accept the browser mic permission prompt. Confirm `● REC` appears and the timer counts up.

- [ ] **Step 3: Speak a factual claim and confirm it lands**

Speak a clear factual claim (e.g. "Berlin hat mehr als drei Millionen Einwohner"). Click **Senden** (or wait one block interval). Confirm the backend logs `Received audio block …` and that a claim appears in pending claims within ~30–60 s.

- [ ] **Step 4: Confirm Stop releases the mic**

Click **Stop**. Confirm the browser's tab recording indicator clears (mic released) and the bar returns to the idle state with the start button.

- [ ] **Step 5: Record the result**

Note the outcome in the session handover. No commit (verification only).

---

## Final verification

- [ ] Full frontend suite green: `cd frontend && bun run test`
- [ ] Frontend builds: `cd frontend && bun run build`
- [ ] Backend lint clean: `uv run ruff check backend/`
- [ ] Backend unit tests green: `uv run pytest backend/tests -m "not integration"`
- [ ] No stale `listener`/`blackhole`/`pyaudio`/`pynput` references outside `docs/superpowers/`: `grep -rn -i "listener\|blackhole\|pyaudio\|pynput" backend/ frontend/src README.md start_dev.sh pyproject.toml`
