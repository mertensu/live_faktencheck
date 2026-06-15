# Quick Check (Phase Q) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a code-gated, single-claim fact-check ("Quick Check") where a user pastes one text quote, it runs through the existing `fact_checker`, the result is persisted and shown in a `ClaimCard`, capped at 3 checks per code (owner code exempt).

**Architecture:** A synchronous `POST /api/quick-check` endpoint (gated by the existing `require_code` dependency) reuses `FactChecker.check_claim_async`, persists via the existing `build_fact_check_dict` + `add_fact_check` under `session_id="quick-<code>"`, and enforces a lifetime quota tracked by two new columns on the `codes` table. A dedicated `/pruefen` React page submits the claim and renders the result with the existing `ClaimCard`; the code's past quick checks are loaded from the already-open `GET /api/fact-checks`.

**Tech Stack:** FastAPI, aiosqlite, PydanticAI (mocked in tests via `TestModel`), pytest (`pytest-asyncio`), React + react-router, Vite/bun.

---

## Background facts (verified against the codebase)

- `require_code` (`backend/auth.py`) returns the full `codes` row as a dict (it does `SELECT *`), so after migration that dict already carries `quick_checks_used` and `quick_check_limit` — no extra read method needed.
- `FactChecker.check_claim_async(speaker, claim, context=None, episode_date=None)` returns a dict with keys `speaker, original_claim, consistency, evidence, sources, double_check, critique_note`. The agent's instructions already inject the current month/year (`fact_checker.py:96`), so passing `episode_date=None` is correct — `sendedatum` is simply left empty.
- `build_fact_check_dict(result_dict, session_id, speaker_fallback="", claim_fallback="")` (`backend/utils.py:19`) maps the checker result to the DB row shape (`sprecher/behauptung/consistency/begruendung/quellen/...`).
- `db.add_fact_check(dict) -> int` inserts and returns the new id; `db.get_fact_check_by_id(id) -> dict|None` returns the `ClaimCard`-shaped row (includes `id`).
- `GET /api/fact-checks?session_id=...` returns a **plain list** of fact-check dicts and is ungated.
- Test fixtures (`backend/tests/conftest.py`): `reset_state` gives a fresh in-memory DB and seeds `add_code("test-code", "tester")`; `client` sends `X-Access-Code: test-code`; `no_auth_client` sends none; `mock_fact_checker` overrides both agents with `TestModel` (no network), returning `mock_fact_check_response` (consistency `"hoch"`, two sources).
- The frontend has **no JS test suite**; frontend tasks are verified with `cd frontend && bun run build`.

---

## File Structure

- **Modify** `backend/database.py` — add `quick_checks_used` / `quick_check_limit` columns (CREATE TABLE + migration), extend `add_code`, add `increment_quick_checks`.
- **Modify** `backend/auth.py` — `parse_access_codes` returns an optional per-code limit; `seed_codes_from_env` passes it to `add_code`.
- **Create** `backend/routers/quick_check.py` — the `POST /api/quick-check` endpoint.
- **Modify** `backend/models.py` — `QuickCheckRequest`.
- **Modify** `backend/app.py` — register the new router.
- **Create** `backend/tests/test_quick_check.py` — DB, parsing/seeding, and endpoint tests.
- **Modify** `backend/tests/test_access_gate.py` — update the 4 existing `parse_access_codes` assertions to the new 3-tuple shape.
- **Modify** `frontend/src/services/api.js` — `submitQuickCheck`, `fetchQuickCheckHistory`.
- **Create** `frontend/src/pages/QuickCheckPage.jsx` — the `/pruefen` screen.
- **Modify** `frontend/src/App.jsx` — add the `/pruefen` route.
- **Modify** `frontend/src/pages/HomePage.jsx` — add a link to `/pruefen`.
- **Modify** `docs/deployment.md` — document the extended `ACCESS_CODES` syntax + owner-exemption step on the VPS.

---

## Task 1: DB schema — quota columns + increment method

**Files:**
- Modify: `backend/database.py` (CREATE TABLE codes ~98-102; migration loop ~106-119; `add_code` ~317-324; add new method near `count_codes` ~347)
- Test: `backend/tests/test_quick_check.py` (create)

- [ ] **Step 1: Write the failing DB tests**

Create `backend/tests/test_quick_check.py`:

```python
"""Tests for Quick Check (Phase Q): codes quota columns, env parsing/seeding,
and the POST /api/quick-check endpoint."""

import pytest

from backend.database import Database


@pytest.fixture
async def fresh_db():
    db = Database(":memory:")
    await db.connect()
    yield db
    await db.close()


# ---------------------------------------------------------------------------
# DB layer: quota columns on `codes`
# ---------------------------------------------------------------------------

async def test_add_code_defaults_limit_to_3_and_used_to_0(fresh_db):
    await fresh_db.add_code("c1", "ulf")
    row = await fresh_db.get_code("c1")
    assert row["quick_checks_used"] == 0
    assert row["quick_check_limit"] == 3


async def test_add_code_accepts_unlimited_via_none(fresh_db):
    await fresh_db.add_code("owner", "ulf", quick_check_limit=None)
    row = await fresh_db.get_code("owner")
    assert row["quick_check_limit"] is None


async def test_add_code_accepts_custom_limit(fresh_db):
    await fresh_db.add_code("c5", "ann", quick_check_limit=5)
    assert (await fresh_db.get_code("c5"))["quick_check_limit"] == 5


async def test_increment_quick_checks(fresh_db):
    await fresh_db.add_code("c1", "ulf")
    await fresh_db.increment_quick_checks("c1")
    await fresh_db.increment_quick_checks("c1")
    assert (await fresh_db.get_code("c1"))["quick_checks_used"] == 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest backend/tests/test_quick_check.py -v`
Expected: FAIL — `quick_checks_used`/`quick_check_limit` KeyError and `increment_quick_checks` AttributeError.

- [ ] **Step 3: Add the columns to CREATE TABLE and the migration loop**

In `backend/database.py`, change the `codes` CREATE TABLE to:

```python
            CREATE TABLE IF NOT EXISTS codes (
                code              TEXT PRIMARY KEY,
                name              TEXT NOT NULL,
                active            INTEGER NOT NULL DEFAULT 1,
                created_at        TEXT NOT NULL,
                quick_checks_used INTEGER NOT NULL DEFAULT 0,
                quick_check_limit INTEGER DEFAULT 3
            );
```

Then, immediately after the existing `fact_checks` migration loop (the `for migration in [...]` block ending with `pass  # Column already exists`), add a second loop for `codes` so pre-existing prod tables get the columns too:

```python
        # Migrations: add Quick Check quota columns to existing codes tables
        for migration in [
            "ALTER TABLE codes ADD COLUMN quick_checks_used INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE codes ADD COLUMN quick_check_limit INTEGER DEFAULT 3",
        ]:
            try:
                await self.db.execute(migration)
                await self.db.commit()
            except Exception:
                pass  # Column already exists
```

- [ ] **Step 4: Extend `add_code` and add `increment_quick_checks`**

Replace the existing `add_code` method with:

```python
    async def add_code(self, code: str, name: str, quick_check_limit: int | None = 3) -> None:
        """Insert an access code (no-op if the code already exists).

        quick_check_limit: lifetime Quick Check cap; None means unlimited.
        """
        from datetime import datetime
        await self.db.execute(
            "INSERT OR IGNORE INTO codes (code, name, active, created_at, quick_check_limit) "
            "VALUES (?, ?, 1, ?, ?)",
            (code, name, datetime.now().isoformat(), quick_check_limit),
        )
        await self.db.commit()
```

Add this method directly after `count_codes` (~line 351):

```python
    async def increment_quick_checks(self, code: str) -> None:
        """Increment the lifetime Quick Check counter for a code by 1."""
        await self.db.execute(
            "UPDATE codes SET quick_checks_used = quick_checks_used + 1 WHERE code = ?",
            (code,),
        )
        await self.db.commit()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest backend/tests/test_quick_check.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Run the full access-gate suite to confirm no regression**

Run: `uv run pytest backend/tests/test_access_gate.py -v`
Expected: PASS — `add_code` default arg keeps existing callers working (note: the 4 `parse_access_codes` tests are still on the old shape and pass until Task 2).

- [ ] **Step 7: Commit**

```bash
git add backend/database.py backend/tests/test_quick_check.py
git commit -m "Phase Q: add Quick Check quota columns + increment to codes table"
```

---

## Task 2: `ACCESS_CODES` extended syntax (`name:code:limit`)

**Files:**
- Modify: `backend/auth.py` (`parse_access_codes` ~14-30; `seed_codes_from_env` ~32-46)
- Test: `backend/tests/test_quick_check.py` (add); `backend/tests/test_access_gate.py` (update 4 existing assertions)

- [ ] **Step 1: Write the failing parse/seed tests**

Append to `backend/tests/test_quick_check.py`:

```python
from backend.auth import parse_access_codes, seed_codes_from_env


# ---------------------------------------------------------------------------
# Env parsing: optional third "limit" field
# ---------------------------------------------------------------------------

def test_parse_access_codes_default_limit_is_3():
    assert parse_access_codes("ulf:s1") == [("ulf", "s1", 3)]


def test_parse_access_codes_unlimited():
    assert parse_access_codes("ulf:s1:unlimited") == [("ulf", "s1", None)]


def test_parse_access_codes_numeric_limit():
    assert parse_access_codes("ulf:s1:5") == [("ulf", "s1", 5)]


def test_parse_access_codes_bad_limit_falls_back_to_default():
    # A non-numeric, non-"unlimited" third field is treated as the default cap.
    assert parse_access_codes("ulf:s1:abc") == [("ulf", "s1", 3)]


async def test_seed_applies_per_code_limit(fresh_db):
    n = await seed_codes_from_env(fresh_db, "ulf:s1:unlimited,anna:s2:5,bob:s3")
    assert n == 3
    assert (await fresh_db.get_code("s1"))["quick_check_limit"] is None
    assert (await fresh_db.get_code("s2"))["quick_check_limit"] == 5
    assert (await fresh_db.get_code("s3"))["quick_check_limit"] == 3
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest backend/tests/test_quick_check.py -k "parse or seed" -v`
Expected: FAIL — current `parse_access_codes` returns 2-tuples.

- [ ] **Step 3: Implement the extended parser + seeding**

Replace `parse_access_codes` in `backend/auth.py`:

```python
DEFAULT_QUICK_CHECK_LIMIT = 3


def parse_access_codes(raw: str | None) -> list[tuple[str, str, int | None]]:
    """Parse ``ACCESS_CODES`` into ``[(name, code, quick_check_limit), ...]``.

    Each entry is ``name:code`` with an optional third field:
      - absent            -> default cap (DEFAULT_QUICK_CHECK_LIMIT)
      - ``unlimited``     -> None (no cap)
      - a positive int    -> that cap
      - anything else     -> default cap
    Malformed entries (no colon, empty name or code) are silently skipped.
    """
    entries: list[tuple[str, str, int | None]] = []
    if not raw:
        return entries
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        parts = [p.strip() for p in entry.split(":")]
        name, code = parts[0], parts[1]
        if not name or not code:
            continue
        limit: int | None = DEFAULT_QUICK_CHECK_LIMIT
        if len(parts) >= 3:
            third = parts[2].lower()
            if third == "unlimited":
                limit = None
            elif third.isdigit():
                limit = int(third)
        entries.append((name, code, limit))
    return entries
```

Update `seed_codes_from_env` to pass the limit (change the loop body only):

```python
    entries = parse_access_codes(raw)
    for name, code, limit in entries:
        await db.add_code(code, name, quick_check_limit=limit)
    return len(entries)
```

(Keep the surrounding `if raw is None` / `count_codes` guard unchanged. Note: the local variable was previously named `pairs`; rename usages to `entries` or keep `pairs` consistently — just make the tuple unpacking 3-wide.)

- [ ] **Step 4: Update the 4 existing parse tests in `test_access_gate.py`**

In `backend/tests/test_access_gate.py`, change the assertions to the 3-tuple shape:

```python
def test_parse_access_codes_basic():
    assert parse_access_codes("ulf:s1,anna:s2") == [("ulf", "s1", 3), ("anna", "s2", 3)]


def test_parse_access_codes_ignores_malformed_and_whitespace():
    assert parse_access_codes(" ulf : s1 , broken , :x , y: ,anna:s2") == [
        ("ulf", "s1", 3),
        ("anna", "s2", 3),
    ]
```

(`test_parse_access_codes_empty` already asserts `== []` — unchanged. `test_seed_codes_from_env_inserts_when_empty` and `test_seed_codes_is_idempotent_when_table_nonempty` don't inspect the tuple shape — unchanged.)

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest backend/tests/test_quick_check.py backend/tests/test_access_gate.py -v`
Expected: PASS (new parse/seed tests + all access-gate tests).

- [ ] **Step 6: Commit**

```bash
git add backend/auth.py backend/tests/test_quick_check.py backend/tests/test_access_gate.py
git commit -m "Phase Q: extend ACCESS_CODES syntax with per-code quick-check limit"
```

---

## Task 3: `POST /api/quick-check` endpoint

**Files:**
- Modify: `backend/models.py` (add `QuickCheckRequest`)
- Create: `backend/routers/quick_check.py`
- Modify: `backend/app.py` (import + `include_router`, ~22 and ~138)
- Test: `backend/tests/test_quick_check.py` (add endpoint tests)

- [ ] **Step 1: Write the failing endpoint tests**

Append to `backend/tests/test_quick_check.py`:

```python
import backend.state as state


# ---------------------------------------------------------------------------
# Endpoint: POST /api/quick-check
# ---------------------------------------------------------------------------

async def test_quick_check_happy_path(client, mock_fact_checker, monkeypatch):
    monkeypatch.setattr("backend.routers.quick_check.get_fact_checker", lambda: mock_fact_checker)

    res = await client.post("/api/quick-check", json={"claim": "Die Inflation lag 2024 bei 2 Prozent."})

    assert res.status_code == 200
    body = res.json()
    fc = body["fact_check"]
    assert fc["behauptung"] == "Test claim statement"  # from mock_fact_check_response.original_claim
    assert fc["consistency"] == "hoch"
    assert fc["id"] > 0
    assert body["limit"] == 3
    assert body["remaining"] == 2
    # persisted under quick-<code> and counted
    stored = await state.get_db().get_fact_checks(session_id="quick-test-code")
    assert len(stored) == 1
    assert (await state.get_db().get_code("test-code"))["quick_checks_used"] == 1


async def test_quick_check_requires_code(no_auth_client):
    res = await no_auth_client.post("/api/quick-check", json={"claim": "x" * 10})
    assert res.status_code == 401


async def test_quick_check_invalid_code(no_auth_client):
    res = await no_auth_client.post(
        "/api/quick-check",
        json={"claim": "x" * 10},
        headers={"X-Access-Code": "nope"},
    )
    assert res.status_code == 403


async def test_quick_check_empty_claim_is_422_and_no_increment(client):
    res = await client.post("/api/quick-check", json={"claim": "   "})
    assert res.status_code == 422
    assert (await state.get_db().get_code("test-code"))["quick_checks_used"] == 0


async def test_quick_check_oversized_claim_is_422(client):
    res = await client.post("/api/quick-check", json={"claim": "x" * 1001})
    assert res.status_code == 422


async def test_quick_check_quota_exhausted_returns_429(client, mock_fact_checker, monkeypatch):
    monkeypatch.setattr("backend.routers.quick_check.get_fact_checker", lambda: mock_fact_checker)
    db = state.get_db()
    # test-code default limit is 3; push used to 3
    for _ in range(3):
        await db.increment_quick_checks("test-code")

    res = await client.post("/api/quick-check", json={"claim": "Eine Behauptung."})
    assert res.status_code == 429
    # no extra row, counter unchanged
    assert await db.get_fact_checks(session_id="quick-test-code") == []
    assert (await db.get_code("test-code"))["quick_checks_used"] == 3


async def test_quick_check_owner_unlimited_never_blocked(client, mock_fact_checker, monkeypatch):
    monkeypatch.setattr("backend.routers.quick_check.get_fact_checker", lambda: mock_fact_checker)
    db = state.get_db()
    # Re-seed test-code as unlimited by replacing it.
    await db.db.execute("UPDATE codes SET quick_check_limit = NULL, quick_checks_used = 99 WHERE code = 'test-code'")
    await db.db.commit()

    res = await client.post("/api/quick-check", json={"claim": "Noch eine Behauptung."})
    assert res.status_code == 200
    assert res.json()["remaining"] is None
    assert res.json()["limit"] is None
```

Note on the service accessor: the backend's fact-checker accessor is
`from backend.services.registry import get_fact_checker` (used in `routers/claims.py` and
`routers/fact_checks.py`). The router imports that symbol, and the test patches it on the
router module (`backend.routers.quick_check.get_fact_checker`) so the real registry/network
is never touched.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest backend/tests/test_quick_check.py -k quick_check -v`
Expected: FAIL — endpoint/router does not exist (404 / import error).

- [ ] **Step 3: Add the request model**

In `backend/models.py`, add (with `field_validator` imported from pydantic):

```python
from pydantic import BaseModel, field_validator


class QuickCheckRequest(BaseModel):
    """A single claim submitted for a one-shot fact-check."""
    claim: str = Field(min_length=1, max_length=1000)

    @field_validator("claim")
    @classmethod
    def _strip_and_require_nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("claim must not be empty")
        return v
```

If `Field` is not already imported in `models.py`, add it to the pydantic import line
(`from pydantic import BaseModel, Field, field_validator`).

- [ ] **Step 4: Create the router**

Create `backend/routers/quick_check.py`:

```python
"""Quick Check (Phase Q): one-shot, code-gated fact-check of a single pasted claim."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import require_code
from backend.models import QuickCheckRequest
from backend.services.registry import get_fact_checker
from backend.utils import build_fact_check_dict
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["quick-check"])


@router.post("/quick-check")
async def quick_check(request: QuickCheckRequest, code: dict = Depends(require_code)):
    limit = code.get("quick_check_limit")        # None => unlimited
    used = code.get("quick_checks_used", 0)
    if limit is not None and used >= limit:
        raise HTTPException(status_code=429, detail="Kontingent aufgebraucht")

    fact_checker = get_fact_checker()
    result = await fact_checker.check_claim_async(speaker="", claim=request.claim)

    db = state.get_db()
    session_id = f"quick-{code['code']}"
    fact_check = build_fact_check_dict(result, session_id, claim_fallback=request.claim)
    new_id = await db.add_fact_check(fact_check)
    await db.increment_quick_checks(code["code"])

    remaining = None if limit is None else max(limit - (used + 1), 0)
    logger.info(f"Quick check by {code['name']}: {result.get('consistency')} (remaining={remaining})")
    return {
        "fact_check": await db.get_fact_check_by_id(new_id),
        "limit": limit,
        "remaining": remaining,
    }
```

- [ ] **Step 5: Register the router in `app.py`**

In `backend/app.py`, add `quick_check` to the routers import (line ~22):

```python
from backend.routers import audio, claims, fact_checks, config, pipeline, sessions, quick_check
```

And add the include near the other `include_router` calls (line ~138):

```python
app.include_router(quick_check.router)
```

- [ ] **Step 6: Run to verify pass**

Run: `uv run pytest backend/tests/test_quick_check.py -v`
Expected: PASS (all DB, parse/seed, and endpoint tests).

- [ ] **Step 7: Run the full backend suite + lint**

Run: `uv run pytest backend/tests -m "not integration" -q && uv run ruff check backend/`
Expected: all pass, ruff clean.

- [ ] **Step 8: Commit**

```bash
git add backend/models.py backend/routers/quick_check.py backend/app.py backend/tests/test_quick_check.py
git commit -m "Phase Q: add POST /api/quick-check endpoint with per-code quota"
```

---

## Task 4: Frontend — api.js helpers

**Files:**
- Modify: `frontend/src/services/api.js`

- [ ] **Step 1: Add the Quick Check helpers**

Append to `frontend/src/services/api.js` (uses existing `BACKEND_URL`, `authHeaders`, `getAccessCode`, `safeJsonParse`):

```javascript
// Submit a single claim for a one-shot fact-check (Phase Q).
export async function submitQuickCheck(claim) {
  const res = await fetch(`${BACKEND_URL}/api/quick-check`, {
    method: 'POST', headers: authHeaders(), body: JSON.stringify({ claim }),
  })
  const data = await safeJsonParse(res, 'submitQuickCheck')
  if (!res.ok) {
    throw new Error(data?.detail || `submitQuickCheck failed (${res.status})`)
  }
  return data  // { fact_check, limit, remaining }
}

// Load this code's past quick checks (open GET, keyed by quick-<code>).
export async function fetchQuickCheckHistory() {
  const code = getAccessCode()
  if (!code) return []
  const res = await fetch(`${BACKEND_URL}/api/fact-checks?session_id=quick-${encodeURIComponent(code)}`, {
    headers: authHeaders(),
  })
  if (!res.ok) return []
  return safeJsonParse(res, 'fetchQuickCheckHistory')
}
```

- [ ] **Step 2: Verify the build**

Run: `cd frontend && bun run build`
Expected: build succeeds, no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.js
git commit -m "Phase Q: add quick-check API helpers"
```

---

## Task 5: Frontend — `/pruefen` page + route + homepage link

**Files:**
- Create: `frontend/src/pages/QuickCheckPage.jsx`
- Modify: `frontend/src/App.jsx` (import + route)
- Modify: `frontend/src/pages/HomePage.jsx` (link to `/pruefen`)

- [ ] **Step 1: Create the page**

Create `frontend/src/pages/QuickCheckPage.jsx` (reuses the `ClaimCard` component and the
`.about-page` / `.new-session-form` / `.form-field` styles already used by `NewSessionPage`):

```jsx
import { useEffect, useState } from 'react'
import { ClaimCard } from '../components/ClaimCard'
import {
  submitQuickCheck,
  fetchQuickCheckHistory,
  getAccessCode,
  setAccessCode,
} from '../services/api'

export function QuickCheckPage() {
  const [claim, setClaim] = useState('')
  const [accessCode, setAccessCodeInput] = useState(getAccessCode())
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [remaining, setRemaining] = useState(null)
  const [limit, setLimit] = useState(null)
  const [history, setHistory] = useState([])

  const loadHistory = async () => setHistory(await fetchQuickCheckHistory())

  useEffect(() => { if (getAccessCode()) loadHistory() }, [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    setResult(null)
    setSubmitting(true)
    setAccessCode(accessCode.trim())
    try {
      const data = await submitQuickCheck(claim.trim())
      setResult(data.fact_check)
      setLimit(data.limit)
      setRemaining(data.remaining)
      setClaim('')
      await loadHistory()
    } catch (err) {
      const msg = err.message || 'Unbekannter Fehler'
      setError(msg)
      if (/401|403|Zugangscode/i.test(msg)) setAccessCode('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="about-page">
      <div className="about-content">
        <h1>Einzelne Behauptung prüfen</h1>
        <p>Füge ein Zitat oder eine Aussage ein und erhalte einen Faktencheck.</p>

        <form onSubmit={handleSubmit} className="new-session-form">
          <div className="form-field">
            <label htmlFor="qc-code">Zugangscode *</label>
            <input
              id="qc-code"
              type="password"
              value={accessCode}
              onChange={e => setAccessCodeInput(e.target.value)}
              required
              autoComplete="off"
              placeholder="Dein persönlicher Zugangscode"
            />
          </div>

          <div className="form-field">
            <label htmlFor="qc-claim">Behauptung *</label>
            <textarea
              id="qc-claim"
              value={claim}
              onChange={e => setClaim(e.target.value)}
              required
              rows={4}
              maxLength={1000}
              placeholder="z.B. Die Inflation lag 2024 bei 2 Prozent."
            />
          </div>

          {error && <div className="claim-error-message">{error}</div>}

          <button type="submit" disabled={submitting}>
            {submitting ? 'Prüfe …' : 'Behauptung prüfen'}
          </button>
        </form>

        {limit !== null && remaining !== null && (
          <p className="quota-note">Noch {remaining} von {limit} Prüfungen übrig.</p>
        )}

        {result && (
          <div className="quick-check-result">
            <h2>Ergebnis</h2>
            <ClaimCard claim={result} />
          </div>
        )}

        {history.length > 0 && (
          <div className="quick-check-history">
            <h2>Frühere Prüfungen</h2>
            {history.map(fc => <ClaimCard key={fc.id} claim={fc} />)}
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Add the route**

In `frontend/src/App.jsx`, add the import alongside the other page imports:

```jsx
import { QuickCheckPage } from './pages/QuickCheckPage'
```

And add the route inside `<Routes>` (before the catch-all `/:episodeKey` route):

```jsx
          <Route path="/pruefen" element={<QuickCheckPage />} />
```

- [ ] **Step 3: Link to it from the homepage**

In `frontend/src/pages/HomePage.jsx`, add a link to `/pruefen`. Use the existing
`react-router-dom` `Link` (import it if not already imported) and place a button/link near
the top of the page content, e.g.:

```jsx
<Link to="/pruefen" className="quick-check-cta">Einzelne Behauptung prüfen</Link>
```

(Match the surrounding markup/classes already used on `HomePage`; this is a single
navigational link, not the full two-button redesign — that is Phase 1b.)

- [ ] **Step 4: Verify the build**

Run: `cd frontend && bun run build`
Expected: build succeeds, no errors.

- [ ] **Step 5: Manual smoke test (local)**

Start the backend with a seeded code and the frontend, then verify in the browser:
- `/pruefen` with no/invalid code → German error, no result.
- valid code + a claim → spinner, then a `ClaimCard` result + "Noch X von 3 übrig".
- reload `/pruefen` → past checks appear under "Frühere Prüfungen".

Run: `./start_dev.sh <episode-key>` (ensure `.env` has `ACCESS_CODES=ulfkai:0311:unlimited`).
Expected: behaviors above hold.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/QuickCheckPage.jsx frontend/src/App.jsx frontend/src/pages/HomePage.jsx
git commit -m "Phase Q: add /pruefen Quick Check page + homepage link"
```

---

## Task 6: Deployment docs

**Files:**
- Modify: `docs/deployment.md`

- [ ] **Step 1: Document the extended syntax + owner exemption**

Add a short subsection to `docs/deployment.md` near the existing access-gate / `ACCESS_CODES`
runbook content:

```markdown
### Quick Check quota (Phase Q)

`ACCESS_CODES` entries accept an optional third field — `name:code:limit`:
- `name:code`            → default cap of 3 lifetime quick checks
- `name:code:unlimited`  → no cap (use for your own owner code)
- `name:code:<n>`        → custom cap

The quota lives on the `codes` table (`quick_checks_used` / `quick_check_limit`); deleting
a quick-check fact-check row does **not** refund quota.

**On the VPS:** the existing live code was seeded before this column existed, so after
deploying it defaults to a cap of 3. To make your owner code unlimited, either update it
in place:

    sqlite3 /opt/fact_check/<db> "UPDATE codes SET quick_check_limit = NULL WHERE name = 'ulfkai';"

or set `ACCESS_CODES=ulfkai:0311:unlimited` in `/opt/fact_check/.env` before the **first**
seeding of a fresh codes table (seeding is idempotent and will not re-run on a populated table).
```

(Confirm the actual DB filename/path used on the VPS from the existing deployment docs and
substitute it for `<db>`.)

- [ ] **Step 2: Commit**

```bash
git add docs/deployment.md
git commit -m "Phase Q: document quick-check quota syntax + VPS owner exemption"
```

---

## Self-Review

**Spec coverage:**
- Synchronous `POST /api/quick-check`, gated → Task 3. ✔
- Claim-text-only input, no speaker/context/date → Task 3 (`check_claim_async(speaker="", claim=...)`, no `episode_date`). ✔
- Persist to `fact_checks` under `quick-<code>`, revisitable → Task 3 (persist) + Task 5 (history fetch). ✔
- Quota 3/code lifetime via counter on `codes` (deletion-proof), owner exempt → Tasks 1–3. ✔
- Extended `ACCESS_CODES` `name:code:limit` syntax → Task 2. ✔
- Errors 401/403/429/422 in German → Task 3 (+ existing `require_code` for 401/403). ✔
- `/pruefen` screen reusing `ClaimCard`, quota indicator, history, homepage link → Tasks 4–5. ✔
- VPS owner-exemption operational note → Task 6. ✔
- Out of scope (background/polling, two-button homepage, Phase 3b, edit/resend) → honored. ✔

**Placeholder scan:** No TBD/TODO; every code step shows full code; the only two
"confirm X" notes (the service accessor name in Task 3 Step 1, the VPS db path in Task 6)
are explicit verification instructions with a default, not gaps.

**Type/name consistency:** `quick_checks_used` / `quick_check_limit` (DB), `quick_check_limit`
param on `add_code`, `increment_quick_checks`, `parse_access_codes` 3-tuple `(name, code, limit)`,
`submitQuickCheck` / `fetchQuickCheckHistory`, response keys `fact_check`/`limit`/`remaining`,
and `session_id="quick-<code>"` are used identically across backend tasks, the endpoint, and
the frontend.
```
