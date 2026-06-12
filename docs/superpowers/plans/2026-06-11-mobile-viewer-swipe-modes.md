# Mobile-First Viewer with Three Modes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the binary Admin/Normal viewer on the FactCheckPage with a mobile-first Review view (one-claim-at-a-time Swipe + a vertical results feed), an "Auto-Prüfung" header toggle backed by a per-session flag, and a discreet ⚙ Pro entry to the unchanged existing AdminView.

**Architecture:** One small backend change — a per-session `auto_check` boolean (DB column + setter endpoint) that the audio/text pipelines consult instead of only the global `AUTO_APPROVE` env var. Everything else is frontend: three new components (`SwipeCard`, `ResultsFeed`, `ReviewView`) plus thin `api.js` helpers wrapping the *existing* claim endpoints; `FactCheckPage` renders `ReviewView` by default and `AdminView` (unchanged) only behind the existing `showAdminMode` gate.

**Tech Stack:** Backend — FastAPI, aiosqlite, pytest. Frontend — React (hooks), Vite, vitest + @testing-library/react. Always `uv` for Python, `bun` for frontend.

---

## Reference: verified facts about the current code (read before starting)

These were confirmed by reading the code; rely on them, don't re-derive:

- **Session storage** lives in `backend/database.py`: table `sessions` (schema at lines ~82-95), `_row_to_session()` (~line 269), `add_session()` (~line 286), `get_session()` (~line 313). Migrations are a list of `ALTER TABLE` strings wrapped in try/except (~line 132 for the `conversation_type` example). SQLite stores booleans as `0/1` INTEGER (see `codes.active`).
- **The viewer read endpoint** is `GET /api/config/{session_id}` (`backend/routers/config.py:67`). It returns `{**session_dict (minus owner_code), speakers, show_name}`. So **any field added to `_row_to_session` automatically appears in this payload** — the frontend can read `config.auto_check` with no further router change.
- **Pipelines** gate auto-approve with `os.getenv("AUTO_APPROVE", "false").lower() == "true"` in two places: `backend/routers/audio.py:189` and `backend/routers/claims.py:111`. The auto branch calls `claim_extractor.select_async(claims, max_claims=3)` → inserts `status="processing"` placeholders → `process_fact_checks_async(...)`. **This selection logic stays unchanged**; only the *condition* changes.
- `backend/routers/audio.py` already loads `session = await db.get_session(session_id)` at ~line 110, so the dict is in scope at the auto-check decision. `backend/routers/claims.py`'s `process_text_pipeline_async` does **not** load the session — it must be added.
- **Existing claim endpoints to reuse (no changes):** `GET /api/pending-claims?session_id=...`, `POST /api/approve-claims` (body `{claims:[{name,claim}], session_id, block_id?}`, gated by `require_code`), `POST /api/discard-claims` (body `{claims:[{name,claim}], session_id}`, **not** gated), `GET /api/fact-checks?session_id=...`.
- **`api.js` has no `approveClaims`/`discardClaims` helpers** — FactCheckPage calls those endpoints with inline `fetch`. The spec's "reuse existing helpers" means we add thin named helpers in `api.js`. `authHeaders()` already exists and injects `X-Access-Code` from localStorage.
- **`ClaimCard` already renders a processing spinner**: `frontend/src/components/ClaimCard.jsx:137` — `export function ClaimCard({ claim, onSelect })`, with a `claim.status === 'processing'` branch (spinner) and a `claim.status === 'error'` branch. ResultsFeed reuses it directly.
- **vitest** is configured in `frontend/vite.config.js` (`test: { environment: 'jsdom', globals: false }`), run with `bun run test` (`vitest run`). `globals:false` ⇒ every test file imports `{ describe, it, expect, vi, ... }` from `'vitest'`. Component testing libs (`@testing-library/react`, `@testing-library/dom`, `jsdom`) are installed. Existing test style refs: `frontend/src/services/api.test.js` (fetch-mock style), `frontend/src/wizard/wizardLogic.test.js` (pure-logic style).
- **Backend test fixtures** (`backend/tests/conftest.py`): `client` (httpx async client, pre-seeds code `test-code` and sends `X-Access-Code: test-code`), `no_auth_client` (no header), in-memory DB. DB-level tests use the `db` fixture pattern in `backend/tests/test_database_sessions.py` (`Database(":memory:")`).
- **`config.py`**: `Episode.from_session_row()` (~line 71) and `episode_to_session_dict()` (~line 241) map between the sessions row and the `Episode` view-model. The pipeline reads `auto_check` from the **session dict**, not from `Episode`, so `Episode` does not need the field; `episode_to_session_dict` (used only for seeding hardcoded public episodes) defaults it to off.

---

## File structure

**Backend (modify):**
- `backend/database.py` — add `auto_check` column + migration; include it in `_row_to_session`/`add_session`; new `set_session_auto_check()` method.
- `backend/models.py` — add `auto_check` to `SessionResponse`; new `AutoCheckRequest`.
- `backend/routers/sessions.py` — new `POST /api/sessions/{session_id}/auto-check` (gated).
- `backend/utils.py` — new pure helper `auto_check_enabled(session)`.
- `backend/routers/audio.py`, `backend/routers/claims.py` — call the helper instead of the bare env check (claims.py also loads the session).

**Frontend (create):**
- `frontend/src/components/SwipeCard.jsx` (+ `.test.jsx`)
- `frontend/src/components/ResultsFeed.jsx` (+ `.test.jsx`)
- `frontend/src/components/ReviewView.jsx` (+ `.test.jsx`)

**Frontend (modify):**
- `frontend/src/services/api.js` (+ tests in `api.test.js`) — `approveClaims`, `discardClaims`, `setSessionAutoCheck`, `fetchPendingClaims`, `fetchFactChecks`.
- `frontend/src/pages/FactCheckPage.jsx` — render `ReviewView` by default; `AdminView` behind ⚙ Pro; relabel toggle to "Pro"/"Zurück".
- `frontend/src/App.css` — swipe card + review layout styles.

---

## Task 1: Backend — `auto_check` column + DB setter

**Files:**
- Modify: `backend/database.py` (schema ~82, migrations ~132, `_row_to_session` ~269, `add_session` ~286)
- Test: `backend/tests/test_database_sessions.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_database_sessions.py`:

```python
async def test_new_session_defaults_auto_check_false(db):
    await db.add_session({"session_id": "ac1", "title": "T", "created_at": "now"})
    s = await db.get_session("ac1")
    assert s["auto_check"] is False


async def test_set_session_auto_check_roundtrips_as_bool(db):
    await db.add_session({"session_id": "ac2", "title": "T", "created_at": "now"})
    changed = await db.set_session_auto_check("ac2", True)
    assert changed is True
    assert (await db.get_session("ac2"))["auto_check"] is True

    await db.set_session_auto_check("ac2", False)
    assert (await db.get_session("ac2"))["auto_check"] is False


async def test_set_session_auto_check_unknown_session_returns_false(db):
    assert await db.set_session_auto_check("nope", True) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_database_sessions.py -k auto_check -v`
Expected: FAIL — `KeyError: 'auto_check'` and `AttributeError: 'Database' object has no attribute 'set_session_auto_check'`.

- [ ] **Step 3: Add the column to the `CREATE TABLE sessions` block**

In `backend/database.py`, inside the `sessions` table definition (after the `conversation_type` line), add:

```sql
                auto_check       INTEGER NOT NULL DEFAULT 0,
```

(Place it before the `status` column for readability; column order only matters for the explicit `INSERT` in `add_session`, which we update below.)

- [ ] **Step 4: Add the migration for existing DBs**

In `backend/database.py`, next to the existing `conversation_type` migration block, add a sibling block:

```python
        # Migration: add auto_check to existing sessions tables
        for migration in [
            "ALTER TABLE sessions ADD COLUMN auto_check INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                await self.db.execute(migration)
                await self.db.commit()
            except Exception:
                pass  # Column already exists
```

- [ ] **Step 5: Surface the column in `_row_to_session` (coerce to bool)**

In `_row_to_session`, add to the returned dict (after `"conversation_type": row["conversation_type"],`):

```python
            "auto_check": bool(row["auto_check"]),
```

- [ ] **Step 6: Include the column in `add_session`'s INSERT**

In `add_session`, update the column list, the `VALUES` placeholders, and the values tuple to include `auto_check` right after `conversation_type`:

- Column list: `... type, conversation_type, auto_check, status, ...`
- Add one more `?` to the `VALUES (...)` list.
- In the values tuple, after the `conversation_type` line add:

```python
                int(session.get("auto_check", False)),
```

- [ ] **Step 7: Add the `set_session_auto_check` method**

In `backend/database.py`, after `end_session`, add:

```python
    async def set_session_auto_check(self, session_id: str, enabled: bool) -> bool:
        """Set the per-session auto_check flag. Returns True if a row was updated."""
        cursor = await self.db.execute(
            "UPDATE sessions SET auto_check = ? WHERE session_id = ?",
            (int(enabled), session_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_database_sessions.py -v`
Expected: PASS (all session DB tests, including the 3 new ones).

- [ ] **Step 9: Commit**

```bash
git add backend/database.py backend/tests/test_database_sessions.py
git commit -m "feat(db): per-session auto_check column + setter"
```

---

## Task 2: Backend — `auto-check` endpoint + SessionResponse field

**Files:**
- Modify: `backend/models.py` (`SessionResponse` ~136; add `AutoCheckRequest`)
- Modify: `backend/routers/sessions.py`
- Test: `backend/tests/test_api_sessions.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api_sessions.py`:

```python
async def test_session_response_includes_auto_check_default_false(client):
    sid = (await client.post("/api/sessions", json={"title": "T"})).json()["session_id"]
    resp = await client.get(f"/api/sessions/{sid}")
    assert resp.json()["auto_check"] is False


async def test_set_auto_check_toggles_flag(client):
    sid = (await client.post("/api/sessions", json={"title": "T"})).json()["session_id"]
    resp = await client.post(f"/api/sessions/{sid}/auto-check", json={"enabled": True})
    assert resp.status_code == 200
    assert resp.json()["auto_check"] is True
    assert (await client.get(f"/api/sessions/{sid}")).json()["auto_check"] is True


async def test_set_auto_check_unknown_session_404(client):
    resp = await client.post("/api/sessions/does-not-exist/auto-check", json={"enabled": True})
    assert resp.status_code == 404


async def test_set_auto_check_requires_code(no_auth_client):
    resp = await no_auth_client.post("/api/sessions/whatever/auto-check", json={"enabled": True})
    assert resp.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_api_sessions.py -k auto_check -v`
Expected: FAIL — `KeyError: 'auto_check'` on the response, and `404`/route-not-found for the POST.

- [ ] **Step 3: Add `auto_check` to `SessionResponse` and a request model**

In `backend/models.py`, inside `class SessionResponse`, after `conversation_type: str = "debate"`, add:

```python
    auto_check: bool = False
```

Add a new request model near `CreateSessionRequest`:

```python
class AutoCheckRequest(BaseModel):
    """Request body for POST /api/sessions/{session_id}/auto-check."""
    enabled: bool
```

- [ ] **Step 4: Add the endpoint**

In `backend/routers/sessions.py`, update the import line to include the new model:

```python
from backend.models import AutoCheckRequest, CreateSessionRequest, SessionResponse
```

Then add, after `end_session`:

```python
@router.post("/sessions/{session_id}/auto-check", response_model=SessionResponse)
async def set_auto_check(
    session_id: str,
    request: AutoCheckRequest,
    code: dict = Depends(require_code),
):
    db = state.get_db()
    if not await db.set_session_auto_check(session_id, request.enabled):
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    logger.info(f"Session {session_id} auto_check set to {request.enabled}")
    return SessionResponse(**await db.get_session(session_id))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_api_sessions.py -v`
Expected: PASS (existing + 4 new tests).

- [ ] **Step 6: Commit**

```bash
git add backend/models.py backend/routers/sessions.py backend/tests/test_api_sessions.py
git commit -m "feat(api): POST /sessions/{id}/auto-check + SessionResponse.auto_check"
```

---

## Task 3: Backend — pipelines consult the per-session flag

**Files:**
- Modify: `backend/utils.py` (new pure helper)
- Modify: `backend/routers/audio.py:189`
- Modify: `backend/routers/claims.py:111` (and load the session in `process_text_pipeline_async`)
- Test: `backend/tests/test_utils_auto_check.py` (new)

- [ ] **Step 1: Write the failing test for the pure helper**

Create `backend/tests/test_utils_auto_check.py`:

```python
import pytest

from backend.utils import auto_check_enabled


def test_enabled_when_session_flag_true_even_without_env(monkeypatch):
    monkeypatch.delenv("AUTO_APPROVE", raising=False)
    assert auto_check_enabled({"auto_check": True}) is True


def test_disabled_when_both_false(monkeypatch):
    monkeypatch.delenv("AUTO_APPROVE", raising=False)
    assert auto_check_enabled({"auto_check": False}) is False
    assert auto_check_enabled(None) is False


def test_env_var_still_forces_enabled(monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE", "true")
    assert auto_check_enabled({"auto_check": False}) is True
    assert auto_check_enabled(None) is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest backend/tests/test_utils_auto_check.py -v`
Expected: FAIL — `ImportError: cannot import name 'auto_check_enabled'`.

- [ ] **Step 3: Implement the helper**

In `backend/utils.py`, ensure `import os` is present at the top (add it if missing), then add:

```python
def auto_check_enabled(session: dict | None) -> bool:
    """True if auto-checking should run for this session.

    Per-session ``auto_check`` flag OR the global ``AUTO_APPROVE`` env var (kept
    for tests/dev). ``session`` may be ``None`` when no session row exists.
    """
    if session and session.get("auto_check"):
        return True
    return os.getenv("AUTO_APPROVE", "false").lower() == "true"
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest backend/tests/test_utils_auto_check.py -v`
Expected: PASS.

- [ ] **Step 5: Use the helper in `audio.py`**

In `backend/routers/audio.py`, add to the imports from utils (currently `from backend.utils import to_dict, truncate`):

```python
from backend.utils import auto_check_enabled, to_dict, truncate
```

Replace the condition at ~line 189:

```python
        if os.getenv("AUTO_APPROVE", "false").lower() == "true":
```

with (note: `session` is already loaded at ~line 110):

```python
        if auto_check_enabled(session):
```

- [ ] **Step 6: Use the helper in `claims.py` (and load the session)**

In `backend/routers/claims.py`, add `auto_check_enabled` to the utils import:

```python
from backend.utils import auto_check_enabled, to_dict, truncate, build_fact_check_dict
```

In `process_text_pipeline_async`, the `db` is fetched just before storing the pending block. Replace the auto-approve condition at ~line 111:

```python
        if os.getenv("AUTO_APPROVE", "false").lower() == "true":
```

with a session lookup + helper call:

```python
        session = await db.get_session(session_id) if session_id else None
        if auto_check_enabled(session):
```

(The `import os` in claims.py may now be unused; only remove it if `ruff check` flags it.)

- [ ] **Step 7: Run the broader backend suite + lint**

Run: `uv run pytest backend/tests -m "not integration" -q`
Expected: PASS (all unit tests, ~239+).
Run: `uv run ruff check backend/`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add backend/utils.py backend/routers/audio.py backend/routers/claims.py backend/tests/test_utils_auto_check.py
git commit -m "feat(pipeline): per-session auto_check gates auto-approve"
```

---

## Task 4: Frontend — `api.js` helpers

**Files:**
- Modify: `frontend/src/services/api.js`
- Test: `frontend/src/services/api.test.js`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/services/api.test.js` (it already imports vitest helpers and mocks `global.fetch`; add the new symbols to the import from `'./api'`):

```javascript
describe('claim + auto-check helpers', () => {
  beforeEach(() => { localStorage.clear(); global.fetch = vi.fn() })
  afterEach(() => { vi.restoreAllMocks() })

  const okJson = (body) => ({
    ok: true, status: 200,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body), url: '',
  })

  it('setSessionAutoCheck POSTs {enabled} with auth header', async () => {
    localStorage.setItem('fc_access_code', 'SECRET')
    global.fetch.mockResolvedValue(okJson({ auto_check: true }))

    const res = await setSessionAutoCheck('sess-1', true)

    const [url, opts] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/sessions\/sess-1\/auto-check$/)
    expect(opts.method).toBe('POST')
    expect(opts.headers['X-Access-Code']).toBe('SECRET')
    expect(JSON.parse(opts.body)).toEqual({ enabled: true })
    expect(res).toEqual({ auto_check: true })
  })

  it('setSessionAutoCheck throws on non-ok', async () => {
    global.fetch.mockResolvedValue({
      ok: false, status: 403, headers: { get: () => 'application/json' },
      text: async () => JSON.stringify({ detail: 'nope' }), url: '',
    })
    await expect(setSessionAutoCheck('s', true)).rejects.toThrow('nope')
  })

  it('approveClaims POSTs claims + session_id with auth header', async () => {
    localStorage.setItem('fc_access_code', 'SECRET')
    global.fetch.mockResolvedValue(okJson({ status: 'processing' }))

    await approveClaims('sess-1', [{ name: 'A', claim: 'X' }])

    const [url, opts] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/approve-claims$/)
    expect(opts.headers['X-Access-Code']).toBe('SECRET')
    const body = JSON.parse(opts.body)
    expect(body.session_id).toBe('sess-1')
    expect(body.claims).toEqual([{ name: 'A', claim: 'X' }])
  })

  it('discardClaims POSTs claims + session_id', async () => {
    global.fetch.mockResolvedValue(okJson({ status: 'discarded' }))

    await discardClaims('sess-1', [{ name: 'A', claim: 'X' }])

    const [url, opts] = global.fetch.mock.calls[0]
    expect(url).toMatch(/\/api\/discard-claims$/)
    const body = JSON.parse(opts.body)
    expect(body.session_id).toBe('sess-1')
    expect(body.claims).toEqual([{ name: 'A', claim: 'X' }])
  })
})
```

Update the existing top-of-file import to add the new functions, e.g.:

```javascript
import { sendAudioBlock, setSessionAutoCheck, approveClaims, discardClaims } from './api'
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && bun run test src/services/api.test.js`
Expected: FAIL — the new helpers are `undefined` / not exported.

- [ ] **Step 3: Implement the helpers**

Append to `frontend/src/services/api.js`:

```javascript
// Toggle the per-session auto-check flag (Review view "Auto-Prüfung").
export async function setSessionAutoCheck(sessionId, enabled) {
  const res = await fetch(`${BACKEND_URL}/api/sessions/${sessionId}/auto-check`, {
    method: 'POST', headers: authHeaders(), body: JSON.stringify({ enabled }),
  })
  const data = await safeJsonParse(res, 'setSessionAutoCheck')
  if (!res.ok) {
    throw new Error(data?.detail || `setSessionAutoCheck failed (${res.status})`)
  }
  return data  // SessionResponse (includes auto_check)
}

// Approve one or more claims for fact-checking (Swipe right).
export async function approveClaims(sessionId, claims) {
  const res = await fetch(`${BACKEND_URL}/api/approve-claims`, {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ claims, session_id: sessionId, block_id: `swipe_${Date.now()}` }),
  })
  const data = await safeJsonParse(res, 'approveClaims')
  if (!res.ok) {
    throw new Error(data?.detail || `approveClaims failed (${res.status})`)
  }
  return data
}

// Discard one or more claims (Swipe left) — recorded with status='discarded'.
export async function discardClaims(sessionId, claims) {
  const res = await fetch(`${BACKEND_URL}/api/discard-claims`, {
    method: 'POST', headers: authHeaders(),
    body: JSON.stringify({ claims, session_id: sessionId }),
  })
  const data = await safeJsonParse(res, 'discardClaims')
  if (!res.ok) {
    throw new Error(data?.detail || `discardClaims failed (${res.status})`)
  }
  return data
}

// Fetch pending claim blocks for a session (open GET).
export async function fetchPendingClaims(sessionId) {
  const res = await fetch(`${BACKEND_URL}/api/pending-claims?session_id=${encodeURIComponent(sessionId)}`, {
    headers: authHeaders(),
  })
  if (!res.ok) return []
  return safeJsonParse(res, 'fetchPendingClaims')
}

// Fetch fact-check results for a session (open GET).
export async function fetchFactChecks(sessionId) {
  const res = await fetch(`${BACKEND_URL}/api/fact-checks?session_id=${encodeURIComponent(sessionId)}`, {
    headers: authHeaders(),
  })
  if (!res.ok) return []
  return safeJsonParse(res, 'fetchFactChecks')
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && bun run test src/services/api.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/api.js frontend/src/services/api.test.js
git commit -m "feat(api): setSessionAutoCheck + approve/discard/fetch claim helpers"
```

---

## Task 5: Frontend — `SwipeCard` component

A single pending claim with gesture + button + inline-edit paths. To keep gesture logic testable in jsdom (which has no real layout/pointer physics), the component exposes the three outcomes through **buttons** ("Verwerfen", "Behalten") and an **edit toggle**; a lightweight pointer-drag handler computes horizontal delta and, past a threshold, calls the same handlers. Tests drive the button/edit paths (the accessible equivalents of the gestures), which is exactly what the spec requires.

**Files:**
- Create: `frontend/src/components/SwipeCard.jsx`
- Test: `frontend/src/components/SwipeCard.test.jsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/SwipeCard.test.jsx`:

```javascript
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SwipeCard } from './SwipeCard'

const claim = { id: 'b-0', name: 'Anna', claim: 'Die Inflation liegt bei 2%.' }

describe('SwipeCard', () => {
  it('renders the claim text, speaker and the remaining counter', () => {
    render(<SwipeCard claim={claim} remaining={3} onKeep={() => {}} onDiscard={() => {}} />)
    expect(screen.getByText('Anna')).toBeDefined()
    expect(screen.getByText(/Inflation liegt bei 2%/)).toBeDefined()
    expect(screen.getByText(/noch 3/i)).toBeDefined()
  })

  it('Behalten calls onKeep with the unedited claim', () => {
    const onKeep = vi.fn()
    render(<SwipeCard claim={claim} remaining={1} onKeep={onKeep} onDiscard={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /behalten/i }))
    expect(onKeep).toHaveBeenCalledWith({ name: 'Anna', claim: 'Die Inflation liegt bei 2%.' })
  })

  it('Verwerfen calls onDiscard with the claim', () => {
    const onDiscard = vi.fn()
    render(<SwipeCard claim={claim} remaining={1} onKeep={() => {}} onDiscard={onDiscard} />)
    fireEvent.click(screen.getByRole('button', { name: /verwerfen/i }))
    expect(onDiscard).toHaveBeenCalledWith({ name: 'Anna', claim: 'Die Inflation liegt bei 2%.' })
  })

  it('edit mode surfaces edited speaker + claim to onKeep', () => {
    const onKeep = vi.fn()
    render(<SwipeCard claim={claim} remaining={1} onKeep={onKeep} onDiscard={() => {}} />)
    fireEvent.click(screen.getByRole('button', { name: /bearbeiten/i }))
    fireEvent.change(screen.getByLabelText(/sprecher/i), { target: { value: 'Bert' } })
    fireEvent.change(screen.getByLabelText(/aussage/i), { target: { value: 'Neu.' } })
    fireEvent.click(screen.getByRole('button', { name: /prüfen/i }))
    expect(onKeep).toHaveBeenCalledWith({ name: 'Bert', claim: 'Neu.' })
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && bun run test src/components/SwipeCard.test.jsx`
Expected: FAIL — cannot resolve `./SwipeCard`.

- [ ] **Step 3: Implement `SwipeCard.jsx`**

Create `frontend/src/components/SwipeCard.jsx`:

```javascript
import { useRef, useState } from 'react'

const SWIPE_THRESHOLD = 90  // px of horizontal drag to commit

export function SwipeCard({ claim, remaining, onKeep, onDiscard }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(claim.name || '')
  const [text, setText] = useState(claim.claim || '')
  const [dx, setDx] = useState(0)
  const startX = useRef(null)

  const keep = () => onKeep({ name, claim: text })
  const discard = () => onDiscard({ name: claim.name || '', claim: claim.claim || '' })

  const onPointerDown = (e) => { startX.current = e.clientX; setDx(0) }
  const onPointerMove = (e) => { if (startX.current !== null) setDx(e.clientX - startX.current) }
  const onPointerUp = () => {
    if (startX.current === null) return
    const delta = dx
    startX.current = null
    setDx(0)
    if (delta > SWIPE_THRESHOLD) keep()
    else if (delta < -SWIPE_THRESHOLD) discard()
  }

  return (
    <div className="swipe-card-wrap">
      <p className="swipe-remaining">noch {remaining}</p>
      <div
        className="swipe-card"
        style={{ transform: `translateX(${dx}px)`, touchAction: 'pan-y' }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {editing ? (
          <div className="swipe-edit">
            <label>
              <span>Sprecher</span>
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              <span>Aussage</span>
              <textarea value={text} onChange={(e) => setText(e.target.value)} />
            </label>
            <button type="button" onClick={keep}>Prüfen</button>
          </div>
        ) : (
          <>
            <p className="swipe-speaker">{claim.name}</p>
            <p className="swipe-claim">{claim.claim}</p>
            <button type="button" className="swipe-edit-toggle" onClick={() => setEditing(true)}>
              Bearbeiten
            </button>
          </>
        )}
      </div>
      <div className="swipe-actions">
        <button type="button" className="swipe-discard" onClick={discard}>Verwerfen</button>
        <button type="button" className="swipe-keep" onClick={keep}>Behalten</button>
      </div>
    </div>
  )
}
```

Note: `<label>` wrapping the input/textarea makes `getByLabelText(/sprecher/i)` and `/aussage/i` resolve in the test.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && bun run test src/components/SwipeCard.test.jsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SwipeCard.jsx frontend/src/components/SwipeCard.test.jsx
git commit -m "feat(ui): SwipeCard — keep/discard/edit a single pending claim"
```

---

## Task 6: Frontend — `ResultsFeed` component

A vertical list of fact-check cards (newest first), reusing the existing `ClaimCard` (which already renders processing spinners and error states).

**Files:**
- Create: `frontend/src/components/ResultsFeed.jsx`
- Test: `frontend/src/components/ResultsFeed.test.jsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/ResultsFeed.test.jsx`:

```javascript
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ResultsFeed } from './ResultsFeed'

describe('ResultsFeed', () => {
  it('shows the empty state when there are no results', () => {
    render(<ResultsFeed factChecks={[]} onSelect={() => {}} />)
    expect(screen.getByText(/noch keine ergebnisse/i)).toBeDefined()
  })

  it('renders one card per fact-check', () => {
    const factChecks = [
      { id: 1, sprecher: 'Anna', behauptung: 'A', consistency: 'hoch', begruendung: 'x', quellen: [], status: 'done' },
      { id: 2, sprecher: 'Bert', behauptung: 'B', consistency: '', begruendung: '', quellen: [], status: 'processing' },
    ]
    render(<ResultsFeed factChecks={factChecks} onSelect={() => {}} />)
    expect(screen.getByText('Anna')).toBeDefined()
    expect(screen.getByText('Bert')).toBeDefined()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && bun run test src/components/ResultsFeed.test.jsx`
Expected: FAIL — cannot resolve `./ResultsFeed`.

- [ ] **Step 3: Implement `ResultsFeed.jsx`**

Create `frontend/src/components/ResultsFeed.jsx`:

```javascript
import { ClaimCard } from './ClaimCard'

// Vertical feed of fact-check result cards, newest first. Reuses ClaimCard,
// which already renders processing spinners and error states.
export function ResultsFeed({ factChecks, onSelect }) {
  if (!factChecks || factChecks.length === 0) {
    return <p className="results-empty">Noch keine Ergebnisse</p>
  }
  const ordered = [...factChecks].sort(
    (a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0)
  )
  return (
    <div className="results-feed">
      {ordered.map((fc) => (
        <ClaimCard key={fc.id} claim={fc} onSelect={onSelect} />
      ))}
    </div>
  )
}
```

Note: `ClaimCard` reads `claim.sprecher`/`claim.behauptung`; verify those field names while implementing (the fact-checks API returns German keys — confirmed by `groupedBySpeaker` using `fc.sprecher`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && bun run test src/components/ResultsFeed.test.jsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ResultsFeed.jsx frontend/src/components/ResultsFeed.test.jsx
git commit -m "feat(ui): ResultsFeed — vertical fact-check results list"
```

---

## Task 7: Frontend — `ReviewView` component

Owns the Auto toggle + the pending-claim cursor; renders `SwipeCard` (Auto off, pending exist), the empty/auto status, and the `ResultsFeed`. Wires gestures to the `api.js` helpers and advances the cursor.

**Files:**
- Create: `frontend/src/components/ReviewView.jsx`
- Test: `frontend/src/components/ReviewView.test.jsx`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/ReviewView.test.jsx` (mocks the api module so no network is hit; the component polls via the helpers):

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../services/api', () => ({
  fetchPendingClaims: vi.fn(),
  fetchFactChecks: vi.fn(),
  approveClaims: vi.fn().mockResolvedValue({}),
  discardClaims: vi.fn().mockResolvedValue({}),
  setSessionAutoCheck: vi.fn().mockResolvedValue({ auto_check: true }),
}))

import * as api from '../services/api'
import { ReviewView } from './ReviewView'

const block = (id, claims) => ({ block_id: id, timestamp: '2026-06-11T10:00:00', claims })

beforeEach(() => {
  vi.clearAllMocks()
  api.fetchPendingClaims.mockResolvedValue([
    block('b1', [{ name: 'Anna', claim: 'A1' }, { name: 'Bert', claim: 'A2' }]),
  ])
  api.fetchFactChecks.mockResolvedValue([])
})

describe('ReviewView', () => {
  it('shows the first pending claim with a remaining counter', async () => {
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    expect(await screen.findByText('Anna')).toBeDefined()
    expect(screen.getByText(/noch 2/i)).toBeDefined()
  })

  it('keep calls approveClaims and advances to the next claim', async () => {
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    await screen.findByText('Anna')
    fireEvent.click(screen.getByRole('button', { name: /behalten/i }))
    await waitFor(() =>
      expect(api.approveClaims).toHaveBeenCalledWith('s1', [{ name: 'Anna', claim: 'A1' }])
    )
    expect(await screen.findByText('Bert')).toBeDefined()
  })

  it('discard calls discardClaims and advances', async () => {
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    await screen.findByText('Anna')
    fireEvent.click(screen.getByRole('button', { name: /verwerfen/i }))
    await waitFor(() =>
      expect(api.discardClaims).toHaveBeenCalledWith('s1', [{ name: 'Anna', claim: 'A1' }])
    )
    expect(await screen.findByText('Bert')).toBeDefined()
  })

  it('toggling Auto calls setSessionAutoCheck and hides the swipe card', async () => {
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    await screen.findByText('Anna')
    fireEvent.click(screen.getByRole('checkbox', { name: /auto-prüfung/i }))
    await waitFor(() => expect(api.setSessionAutoCheck).toHaveBeenCalledWith('s1', true))
    expect(screen.getByText(/handy kann liegen bleiben/i)).toBeDefined()
    expect(screen.queryByText('Anna')).toBeNull()
  })

  it('shows the waiting state when there are no pending claims (Auto off)', async () => {
    api.fetchPendingClaims.mockResolvedValue([])
    render(<ReviewView sessionId="s1" initialAutoCheck={false} />)
    expect(await screen.findByText(/warte auf aussagen/i)).toBeDefined()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && bun run test src/components/ReviewView.test.jsx`
Expected: FAIL — cannot resolve `./ReviewView`.

- [ ] **Step 3: Implement `ReviewView.jsx`**

Create `frontend/src/components/ReviewView.jsx`:

```javascript
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchPendingClaims, fetchFactChecks,
  approveClaims, discardClaims, setSessionAutoCheck,
} from '../services/api'
import { SwipeCard } from './SwipeCard'
import { ResultsFeed } from './ResultsFeed'

const POLL_MS = 2000

// Flatten pending blocks (oldest first) into a flat claim queue with stable ids.
const flatten = (blocks) => {
  const out = []
  blocks.forEach((b) =>
    (b.claims || []).forEach((c, i) =>
      out.push({ id: `${b.block_id}-${i}`, name: c.name || '', claim: c.claim || '', timestamp: b.timestamp })
    )
  )
  return out.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
}

export function ReviewView({ sessionId, initialAutoCheck = false, onSelect }) {
  const [auto, setAuto] = useState(initialAutoCheck)
  const [pending, setPending] = useState([])
  const [factChecks, setFactChecks] = useState([])
  const [handledIds, setHandledIds] = useState(() => new Set())
  const [error, setError] = useState(null)
  const handledRef = useRef(handledIds)
  handledRef.current = handledIds

  // Poll pending claims (only meaningful when Auto is off).
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const blocks = await fetchPendingClaims(sessionId)
        if (alive) setPending(flatten(blocks).filter((c) => !handledRef.current.has(c.id)))
      } catch { /* keep last state */ }
    }
    tick()
    const t = setInterval(tick, POLL_MS)
    return () => { alive = false; clearInterval(t) }
  }, [sessionId])

  // Poll fact-check results for the feed.
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const data = await fetchFactChecks(sessionId)
        if (alive) setFactChecks(data.filter((fc) => fc.status !== 'discarded'))
      } catch { /* keep last state */ }
    }
    tick()
    const t = setInterval(tick, POLL_MS)
    return () => { alive = false; clearInterval(t) }
  }, [sessionId])

  const current = pending[0]

  const advance = useCallback((id) => {
    setHandledIds((prev) => new Set(prev).add(id))
    setPending((prev) => prev.filter((c) => c.id !== id))
  }, [])

  const handleKeep = useCallback(async (edited) => {
    if (!current) return
    try {
      await approveClaims(sessionId, [edited])
      setError(null)
      advance(current.id)
    } catch (e) {
      setError('Konnte nicht senden — bitte erneut versuchen.')
    }
  }, [current, sessionId, advance])

  const handleDiscard = useCallback(async (claim) => {
    if (!current) return
    try {
      await discardClaims(sessionId, [claim])
      setError(null)
      advance(current.id)
    } catch (e) {
      setError('Konnte nicht verwerfen — bitte erneut versuchen.')
    }
  }, [current, sessionId, advance])

  const handleToggleAuto = useCallback(async (e) => {
    const next = e.target.checked
    setAuto(next)
    try {
      await setSessionAutoCheck(sessionId, next)
    } catch {
      setAuto(!next)  // revert on failure
      setError('Auto-Prüfung konnte nicht umgeschaltet werden.')
    }
  }, [sessionId])

  return (
    <div className="review-view">
      <div className="review-controls">
        <label className="auto-toggle">
          <input type="checkbox" checked={auto} onChange={handleToggleAuto} />
          <span>Auto-Prüfung</span>
        </label>
      </div>

      {error && <p className="review-error" role="alert">{error}</p>}

      <div className="review-stage">
        {auto ? (
          <p className="review-auto-status">Automatisch — Handy kann liegen bleiben</p>
        ) : current ? (
          <SwipeCard
            key={current.id}
            claim={current}
            remaining={pending.length}
            onKeep={handleKeep}
            onDiscard={handleDiscard}
          />
        ) : (
          <p className="review-waiting">Warte auf Aussagen…</p>
        )}
      </div>

      <ResultsFeed factChecks={factChecks} onSelect={onSelect} />
    </div>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && bun run test src/components/ReviewView.test.jsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ReviewView.jsx frontend/src/components/ReviewView.test.jsx
git commit -m "feat(ui): ReviewView — swipe queue + auto toggle + results feed"
```

---

## Task 8: Frontend — wire `ReviewView` into `FactCheckPage` + Pro toggle

Render `ReviewView` as the default for everyone; show `AdminView` (unchanged) only when the ⚙ Pro toggle is active AND `showAdminMode` is satisfied. Relabel the existing button to "Pro" / "Zurück". Read `auto_check` from the config payload to initialise the toggle.

**Files:**
- Modify: `frontend/src/pages/FactCheckPage.jsx`

- [ ] **Step 1: Import the new component and capture `auto_check` from config**

In `frontend/src/pages/FactCheckPage.jsx`, add the import:

```javascript
import { ReviewView } from '../components/ReviewView'
```

Add a state for the initial auto flag near the other `useState`s:

```javascript
  const [initialAutoCheck, setInitialAutoCheck] = useState(false)
```

In `loadEpisodeConfig`, after the `setDisplayTitle` block, capture the flag:

```javascript
          if (typeof config.auto_check === 'boolean') {
            setInitialAutoCheck(config.auto_check)
          }
```

- [ ] **Step 2: Relabel the mode button**

Replace the toggle label text:

```javascript
              {isAdminMode ? 'Normal-Modus' : 'Admin-Modus'}
```

with:

```javascript
              {isAdminMode ? 'Zurück' : 'Pro'}
```

(Optionally add the gear glyph: `{isAdminMode ? 'Zurück' : '⚙ Pro'}`.)

- [ ] **Step 3: Render `ReviewView` as the default branch**

Replace the `else` branch of the `isAdminMode ? (...) : (...)` block in the `return` (the branch currently rendering `BackendErrorDisplay` + `SpeakerColumns` + `ClaimDetailOverlay`) with the Review view. The new non-admin branch:

```javascript
          <>
            <BackendErrorDisplay error={backendError} />
            <ReviewView
              sessionId={episodeKey}
              initialAutoCheck={initialAutoCheck}
              onSelect={setSelectedClaim}
            />
            {selectedClaim && (
              <ClaimDetailOverlay
                claim={selectedClaim}
                onClose={() => setSelectedClaim(null)}
              />
            )}
          </>
```

The `isAdminMode` branch (RecordingBar + AdminView) is unchanged. `SpeakerColumns` import may now be unused — remove the import line only if `bun run build`/lint flags it; otherwise leave it (spec keeps `SpeakerColumns` in the codebase).

- [ ] **Step 4: Verify the build and full frontend test run**

Run: `cd frontend && bun run test`
Expected: PASS (all suites: api, wizardLogic, useAudioRecorder, SwipeCard, ResultsFeed, ReviewView).
Run: `cd frontend && bun run build`
Expected: build succeeds, no unresolved imports.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/FactCheckPage.jsx
git commit -m "feat(ui): ReviewView is the default viewer; mode button -> Pro/Zurück"
```

---

## Task 9: Frontend — styles for the Review view

Mobile-first CSS for the swipe card, controls, auto/waiting status, and results feed. No test (pure CSS); verified in the manual click-test.

**Files:**
- Modify: `frontend/src/App.css`

- [ ] **Step 1: Append the styles**

Append to `frontend/src/App.css`:

```css
/* ===== Mobile Review view (Swipe / Auto / results feed) ===== */
.review-view { max-width: 640px; margin: 0 auto; padding: 0 1rem 2rem; }
.review-controls { display: flex; justify-content: flex-end; padding: 0.75rem 0; }
.auto-toggle { display: inline-flex; align-items: center; gap: 0.5rem; cursor: pointer; font-weight: 600; }
.auto-toggle input { width: 1.1rem; height: 1.1rem; }

.review-error { color: #ef4444; margin: 0.25rem 0; font-size: 0.9rem; }
.review-stage { min-height: 220px; display: flex; align-items: center; justify-content: center; }
.review-auto-status,
.review-waiting { text-align: center; color: #6b7280; font-size: 1.05rem; padding: 2rem 1rem; }

.swipe-card-wrap { width: 100%; }
.swipe-remaining { text-align: center; color: #6b7280; font-size: 0.85rem; margin: 0 0 0.5rem; }
.swipe-card {
  background: #fff; border: 1px solid #e5e7eb; border-radius: 16px;
  padding: 1.25rem; box-shadow: 0 4px 16px rgba(0,0,0,0.06);
  transition: transform 0.05s linear; user-select: none;
}
.swipe-speaker { font-weight: 700; margin: 0 0 0.4rem; }
.swipe-claim { margin: 0 0 0.75rem; line-height: 1.5; }
.swipe-edit-toggle {
  background: none; border: none; color: #2563eb; cursor: pointer;
  padding: 0; font-size: 0.9rem;
}
.swipe-edit label { display: block; margin-bottom: 0.6rem; }
.swipe-edit label span { display: block; font-size: 0.8rem; color: #6b7280; margin-bottom: 0.2rem; }
.swipe-edit input,
.swipe-edit textarea {
  width: 100%; padding: 0.5rem; border: 1px solid #d1d5db; border-radius: 8px; font: inherit;
}
.swipe-edit textarea { min-height: 4rem; resize: vertical; }

.swipe-actions { display: flex; gap: 0.75rem; margin-top: 1rem; }
.swipe-actions button { flex: 1; padding: 0.75rem; border-radius: 12px; border: none; font-weight: 600; cursor: pointer; }
.swipe-discard { background: #fee2e2; color: #b91c1c; }
.swipe-keep { background: #dcfce7; color: #15803d; }

.results-feed { display: flex; flex-direction: column; gap: 1rem; margin-top: 1.5rem; }
.results-empty { text-align: center; color: #6b7280; margin-top: 1.5rem; }
```

- [ ] **Step 2: Verify the build still succeeds**

Run: `cd frontend && bun run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/App.css
git commit -m "style: mobile Review view (swipe card, controls, results feed)"
```

---

## Task 10: Full verification + manual click-test

- [ ] **Step 1: Backend unit tests + lint**

Run: `uv run pytest backend/tests -m "not integration" -q`
Expected: PASS (all, including the new DB/API/utils tests).
Run: `uv run ruff check backend/`
Expected: no errors.

- [ ] **Step 2: Frontend tests + build**

Run: `cd frontend && bun run test`
Expected: PASS (all suites).
Run: `cd frontend && bun run build`
Expected: build succeeds, no `frontend/dist/` committed (per project rule).

- [ ] **Step 3: Manual click-test (per spec)**

Start dev (`./start_dev.sh <episode-key>`), then on a phone or narrow viewport:
1. Default view is the Review view (one SwipeCard at a time, "noch N" counter, results feed below).
2. Record a short conversation via the recorder (Pro/admin bar) so pending claims arrive.
3. Swipe/Behalten one claim → it leaves the queue, a processing card appears in the feed, then a result.
4. Verwerfen one claim → it leaves the queue, no fact-check result for it.
5. Tap Bearbeiten, change speaker/text, Prüfen → edited claim is checked.
6. Toggle **Auto-Prüfung** on → swipe card is replaced by "Handy kann liegen bleiben"; with the env unset, new blocks get auto-checked (≤3 per block) and land in the feed without interaction. Reload the page → the toggle is still on (persisted via `auto_check`).
7. Click **⚙ Pro** (gate satisfied on localhost) → the existing AdminView still works (pending/staging/send, pipeline status). Button now reads **Zurück**; click it to return to Review.

- [ ] **Step 4: Final commit (if the manual test required tweaks)**

```bash
git add -A
git commit -m "polish: review-view manual test fixes"
```

---

## Self-Review (completed during planning)

**Spec coverage:**
- Default Review view for everyone → Tasks 7–8. ✅
- Swipe semantics (right=approve+check, left=discard, tap=edit-then-check) → Task 5 (`SwipeCard`) + Task 7 wiring (`approveClaims`/`discardClaims`). ✅
- One card at a time + "noch N" counter → Task 5/7. ✅
- Auto mode header toggle, off by default, calm status, reuses `select_async(≤3)` → Task 1–3 (per-session flag drives the *existing* auto branch) + Task 7 toggle. ✅
- Pro = existing `AdminView` unchanged via discreet entry, gated by `showAdminMode`; button "Pro"/"Zurück" → Task 8. ✅
- Vertical results feed (newest first, processing spinner) replacing `SpeakerColumns` on the viewer; `SpeakerColumns` not deleted → Task 6 + Task 8 (import left in place). ✅
- Backend: single change = per-session `auto_check` flag (column, setter endpoint gated by `require_code`, surfaced on the read endpoint via `_row_to_session` → `/api/config/{id}`) → Tasks 1–3. ✅
- Error/empty states (failed keep/discard leaves card + inline message; failed toggle reverts; "Warte auf Aussagen…", "Noch keine Ergebnisse", auto status) → Tasks 5–7. ✅
- Testing: SwipeCard, ReviewView, `api.setSessionAutoCheck`, backend pipeline-branch + gated endpoint → Tasks 1–7. ✅

**Out-of-scope respected:** no undo, no card-stack animation, no real roles/auth, no desktop polish, `SpeakerColumns` kept. ✅

**Type/name consistency:** `onKeep`/`onDiscard` take `{ name, claim }`; `approveClaims(sessionId, claims[])` / `discardClaims(sessionId, claims[])` / `setSessionAutoCheck(sessionId, enabled)` signatures match across api.js, ReviewView, and their tests. DB `auto_check` is `0/1` in SQLite, coerced to `bool` in `_row_to_session`, surfaced as `auto_check: bool` in `SessionResponse` and `/api/config/{id}`; frontend reads `config.auto_check`. `set_session_auto_check(session_id, enabled)` returns `bool` (used for the 404 path). ✅

**Note for the implementer:** Confirm `ClaimCard`'s exact field reads (`claim.sprecher` / `claim.behauptung` / `claim.status`) when building `ResultsFeed` (Task 6) — they were verified against `groupedBySpeaker` but re-check the component body.
