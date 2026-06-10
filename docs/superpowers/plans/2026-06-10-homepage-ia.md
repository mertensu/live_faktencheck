# Homepage / Informationsarchitektur (Phase 1b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dual-variant homepage with a single balanced landing page — pitch → one access-code unlock → two equal action cards (Quick Check + Live Session) → examples section — backed by a new cheap `GET /api/validate-code` endpoint.

**Architecture:** A new side-effect-free `GET /api/validate-code` endpoint reuses the existing `require_code` dependency to validate a code and return only public fields. The frontend gets a `validateCode()` api helper, a small `AccessUnlock` component that gates the two action cards, and a rewritten `HomePage.jsx` (no more `isProduction` branch). The access code is shared via the existing `localStorage` mechanism, so flow pages (`/pruefen`, `/new`) need no changes and keep their own code field as a deep-link fallback.

**Tech Stack:** FastAPI (backend, pytest), React + react-router-dom (frontend, built with `bun run build`), plain CSS in `App.css`.

---

## File Structure

**Backend**
- `backend/routers/config.py` — add `GET /api/validate-code` (cheap, gated status endpoint, next to `/api/health`).
- `backend/tests/test_access_gate.py` — add endpoint tests (200 / 401 / 403, no raw code, side-effect-free).

**Frontend**
- `frontend/src/services/api.js` — add `validateCode(code)` helper.
- `frontend/src/components/AccessUnlock.jsx` — **new** component: code input + unlock button + locked/unlocked state, exposes unlocked status to parent.
- `frontend/src/pages/HomePage.jsx` — full rewrite: hero + unlock + two action cards + examples section.
- `frontend/src/components/Navigation.jsx` — add optional "Beispiele" anchor link.
- `frontend/src/App.css` — new classes (hero, unlock, action cards incl. locked + beta tag, examples) + the Phase-Q leftover classes (`quota-note`, `quick-check-result`, `quick-check-history`); remove the obsolete `quick-check-cta` rule.

**Docs**
- `docs/superpowers/ROADMAP-session-app.md` — mark Phase 1b ✅ after completion.

---

## Task 1: Backend — `GET /api/validate-code` endpoint

**Files:**
- Modify: `backend/routers/config.py` (add endpoint after the `/health` route, ~line 95)
- Test: `backend/tests/test_access_gate.py` (add tests at end of file)

**Context:** The `codes` table row (`backend/database.py:97-104`) has columns: `code, name, active, created_at, quick_checks_used, quick_check_limit`. The response must expose **only** `name`, `quick_check_limit`, `quick_checks_used` — never `code` (raw secret) or `active`. The `require_code` dependency (`backend/auth.py:65`) raises 401 on missing header, 403 on unknown/inactive code, and returns the full row dict on success. Test fixtures: `client` (sends `X-Access-Code: test-code`), `no_auth_client` (no header), `TEST_ACCESS_CODE = "test-code"` seeded with name `"tester"` and default `quick_check_limit=3` (see `backend/tests/conftest.py`).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_access_gate.py`:

```python
# =============================================================================
# GET /api/validate-code (cheap, side-effect-free code check)
# =============================================================================

async def test_validate_code_valid_returns_public_fields(client):
    resp = await client.get("/api/validate-code")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "tester"
    assert body["quick_check_limit"] == 3
    assert body["quick_checks_used"] == 0


async def test_validate_code_does_not_leak_raw_code_or_active(client):
    body = (await client.get("/api/validate-code")).json()
    assert "code" not in body
    assert "active" not in body
    assert "created_at" not in body


async def test_validate_code_without_header_is_401(no_auth_client):
    resp = await no_auth_client.get("/api/validate-code")
    assert resp.status_code == 401


async def test_validate_code_with_invalid_code_is_403(no_auth_client):
    resp = await no_auth_client.get(
        "/api/validate-code", headers={"X-Access-Code": "wrong"}
    )
    assert resp.status_code == 403


async def test_validate_code_is_side_effect_free(client):
    """A validate call must not consume Quick Check quota or otherwise write."""
    import backend.state as state

    before = (await state.get_db().get_code(TEST_ACCESS_CODE))["quick_checks_used"]
    await client.get("/api/validate-code")
    after = (await state.get_db().get_code(TEST_ACCESS_CODE))["quick_checks_used"]
    assert before == after == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_access_gate.py -k validate_code -v`
Expected: FAIL — all five with 404 (route not found) on the request assertions.

- [ ] **Step 3: Implement the endpoint**

In `backend/routers/config.py`, update the imports near the top to add the dependency:

```python
from fastapi import APIRouter, HTTPException, Depends

from backend.auth import require_code
```

Then add this route immediately after the `health()` function (end of file):

```python
@router.get('/validate-code')
async def validate_code(code: dict = Depends(require_code)):
    """Cheaply validate an access code.

    Reuses ``require_code`` (missing header -> 401, unknown/inactive -> 403).
    Side-effect-free: no DB write, no paid external call. Returns only public
    fields — never the raw code or internal flags.
    """
    return {
        "name": code["name"],
        "quick_check_limit": code["quick_check_limit"],
        "quick_checks_used": code["quick_checks_used"],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_access_gate.py -k validate_code -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the full access-gate suite + lint**

Run: `uv run pytest backend/tests/test_access_gate.py -v && uv run ruff check backend/`
Expected: all pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/config.py backend/tests/test_access_gate.py
git commit -m "Phase 1b: add GET /api/validate-code endpoint"
```

---

## Task 2: Frontend — `validateCode()` api helper

**Files:**
- Modify: `frontend/src/services/api.js` (append after `fetchQuickCheckHistory`, ~line 111)

**Context:** Existing helpers (`createSession`, `submitQuickCheck`) follow a fixed pattern: call `fetch` with `authHeaders()`, parse via `safeJsonParse`, throw `data?.detail || "... failed (status)"` on non-ok. `authHeaders()` reads the code from `localStorage`. For unlock we need to validate an **arbitrary** code the user just typed (not yet stored), so this helper sends the code via an explicit `X-Access-Code` header argument rather than relying on `authHeaders()`.

- [ ] **Step 1: Implement the helper**

Append to `frontend/src/services/api.js`:

```javascript
// Cheaply validate an access code without storing it (Phase 1b homepage unlock).
// Returns { name, quick_check_limit, quick_checks_used } or throws on non-ok.
export async function validateCode(code) {
  const res = await fetch(`${BACKEND_URL}/api/validate-code`, {
    headers: { ...FETCH_HEADERS, 'X-Access-Code': code },
  })
  const data = await safeJsonParse(res, 'validateCode')
  if (!res.ok) {
    throw new Error(data?.detail || `validateCode failed (${res.status})`)
  }
  return data
}
```

- [ ] **Step 2: Verify the build still compiles**

Run: `cd frontend && bun run build`
Expected: build succeeds (no syntax/import errors).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.js
git commit -m "Phase 1b: add validateCode api helper"
```

---

## Task 3: Frontend — `AccessUnlock` component

**Files:**
- Create: `frontend/src/components/AccessUnlock.jsx`

**Context:** This component owns the unlock UI and lifts the unlocked state up via an `onUnlock` callback so `HomePage` can switch the action cards between locked and unlocked. On mount, if `getAccessCode()` already returns a code, the page renders unlocked immediately (no re-typing). Mirror the error handling in `QuickCheckPage.jsx:39-45`: on a 401/403/"Zugangscode" error, clear the stored code and the input. The component does **not** navigate — it only manages unlock state.

The parent passes a `ref` so it can focus the input when a locked card is clicked (spec: clicking a locked card focuses the code field). Use `forwardRef` + `useImperativeHandle` to expose a `focus()` method.

- [ ] **Step 1: Create the component**

Create `frontend/src/components/AccessUnlock.jsx`:

```jsx
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { validateCode, getAccessCode, setAccessCode } from '../services/api'

export const AccessUnlock = forwardRef(function AccessUnlock({ unlocked, name, onUnlock }, ref) {
  const [code, setCode] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const inputRef = useRef(null)

  useImperativeHandle(ref, () => ({
    focus: () => inputRef.current?.focus(),
  }))

  // Render unlocked immediately if a code is already stored.
  useEffect(() => {
    const stored = getAccessCode()
    if (stored && !unlocked) onUnlock(stored, null)
  }, [unlocked, onUnlock])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    const trimmed = code.trim()
    try {
      const data = await validateCode(trimmed)
      setAccessCode(trimmed)
      onUnlock(trimmed, data?.name ?? null)
      setCode('')
    } catch (err) {
      const msg = err.message || 'Unbekannter Fehler'
      setError(/401|403|Zugangscode/i.test(msg) ? 'Ungültiger Zugangscode' : msg)
      setCode('')
    } finally {
      setSubmitting(false)
    }
  }

  if (unlocked) {
    return (
      <section className="access-unlock access-unlock--done">
        <p className="access-unlock-status">
          Freigeschaltet{name ? ` als ${name}` : ''}.
        </p>
      </section>
    )
  }

  return (
    <section className="access-unlock">
      <form onSubmit={handleSubmit} className="access-unlock-form">
        <input
          ref={inputRef}
          type="password"
          value={code}
          onChange={e => setCode(e.target.value)}
          autoComplete="off"
          placeholder="Zugangscode"
          aria-label="Zugangscode"
          className="access-unlock-input"
        />
        <button type="submit" className="action-button primary" disabled={submitting}>
          {submitting ? 'Prüfe …' : 'Freischalten'}
        </button>
      </form>
      {error && <p className="form-error">{error}</p>}
    </section>
  )
})
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd frontend && bun run build`
Expected: build succeeds (component is not yet imported anywhere — this only checks the file is valid; bun/vite tree-shakes unused modules, so confirm no syntax error is reported).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/AccessUnlock.jsx
git commit -m "Phase 1b: add AccessUnlock component"
```

---

## Task 4: Frontend — rewrite `HomePage.jsx`

**Files:**
- Modify: `frontend/src/pages/HomePage.jsx` (full rewrite)

**Context:** Remove the `isProduction` branch entirely. Compose four stacked blocks: Hero, `AccessUnlock`, two action cards, examples section. Reuse the existing `getEpisodeDisplayName` helper and the `show-item` list markup (keep the `test` filter, drop TV/YouTube grouping → flat list). Action cards: when locked, render as `aria-disabled` buttons that focus the unlock input on click; when unlocked, render as `<Link>`. The examples section gets `id="beispiele"` so the nav anchor (Task 5) can scroll to it.

- [ ] **Step 1: Rewrite the file**

Replace the entire contents of `frontend/src/pages/HomePage.jsx`:

```jsx
import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useShows } from '../hooks/useShows'
import { AccessUnlock } from '../components/AccessUnlock'
import { getAccessCode } from '../services/api'

function getEpisodeDisplayName(show) {
  if (typeof show === 'object') {
    if (show.episode_name) {
      // Strip date prefix from episode_name (format: "DD. Month YYYY - Guests")
      let episodePart = show.episode_name
      if (show.date && episodePart.startsWith(show.date + ' - ')) {
        episodePart = episodePart.slice((show.date + ' - ').length)
      } else if (show.date && episodePart === show.date) {
        episodePart = null
      }
      return episodePart ? `${show.name} - Gäste: ${episodePart}` : show.name
    }
    if (show.name) return show.name
  }
  if (typeof show === 'string') return show.charAt(0).toUpperCase() + show.slice(1)
  return 'Unknown Show'
}

function ActionCard({ to, icon, title, description, beta, unlocked, onLockedClick }) {
  const inner = (
    <>
      <div className="action-card-head">
        <span className="action-card-icon" aria-hidden="true">{icon}</span>
        <span className="action-card-title">{title}</span>
        {beta && <span className="beta-tag">beta</span>}
        {!unlocked && <span className="action-card-lock" aria-hidden="true">🔒</span>}
      </div>
      <p className="action-card-desc">{description}</p>
    </>
  )

  if (unlocked) {
    return <Link to={to} className="action-card">{inner}</Link>
  }
  return (
    <button
      type="button"
      className="action-card action-card--locked"
      aria-disabled="true"
      onClick={onLockedClick}
    >
      {inner}
    </button>
  )
}

export function HomePage() {
  const { shows, loading } = useShows()
  const [unlocked, setUnlocked] = useState(Boolean(getAccessCode()))
  const [name, setName] = useState(null)
  const unlockRef = useRef(null)

  const handleUnlock = (_code, unlockedName) => {
    setUnlocked(true)
    setName(unlockedName)
  }

  const focusUnlock = () => unlockRef.current?.focus()

  const visibleShows = shows.filter(s => (s.key || s) !== 'test')

  return (
    <div className="home-page">
      <section className="hero-section">
        <h1 className="hero-title">Live-Faktencheck</h1>
        <p className="hero-subtitle">KI-gestützte Einordnung im Minutentakt.</p>
      </section>

      <AccessUnlock
        ref={unlockRef}
        unlocked={unlocked}
        name={name}
        onUnlock={handleUnlock}
      />

      <section className="action-cards">
        <ActionCard
          to="/pruefen"
          icon="🔎"
          title="Behauptung prüfen"
          description="Ein Zitat oder eine Aussage einfügen und sofort einen Faktencheck erhalten."
          unlocked={unlocked}
          onLockedClick={focusUnlock}
        />
        <ActionCard
          to="/new"
          icon="🎙"
          title="Live-Session starten"
          description="Eine Sendung live mitschneiden und Aussagen in Echtzeit prüfen."
          beta
          unlocked={unlocked}
          onLockedClick={focusUnlock}
        />
      </section>

      <section className="examples-section" id="beispiele">
        <h2 className="examples-title">Beispiele</h2>
        <p className="examples-intro">Frühere Faktenchecks als Vertrauensbeleg.</p>
        {loading ? (
          <div className="loading-container">
            <div className="loading-spinner"></div>
          </div>
        ) : visibleShows.length > 0 ? (
          <div className="shows-list">
            {visibleShows.map(show => {
              const episodeKey = show.key || show
              const showInfo = show.date || ''
              return (
                <Link key={episodeKey} to={`/${episodeKey}`} className="show-item">
                  <div className="show-item-content">
                    <div className="show-name-row">
                      <span className="show-name">{getEpisodeDisplayName(show)}</span>
                      {show.live && <span className="live-badge">LIVE</span>}
                    </div>
                    {showInfo && <span className="show-info">{showInfo}</span>}
                  </div>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M9 18l6-6-6-6" />
                  </svg>
                </Link>
              )
            })}
          </div>
        ) : (
          <div className="coming-soon-badge">Coming soon</div>
        )}
      </section>
    </div>
  )
}
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd frontend && bun run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/HomePage.jsx
git commit -m "Phase 1b: rewrite HomePage as single balanced landing"
```

---

## Task 5: Frontend — "Beispiele" nav link

**Files:**
- Modify: `frontend/src/components/Navigation.jsx`

**Context:** Add a "Beispiele" link that anchors to the examples section (`#beispiele`) on the homepage. Logo + About stay. Use `<Link to="/#beispiele">` so it works from any route (navigates home, then the browser jumps to the anchor). `/trusted-domains` stays out of the nav (unchanged).

- [ ] **Step 1: Add the link**

In `frontend/src/components/Navigation.jsx`, replace the `nav-links` div:

```jsx
        <div className="nav-links">
          <Link to="/#beispiele">Beispiele</Link>
          <Link to="/about" className={location.pathname === '/about' ? 'active' : ''}>
            About
          </Link>
        </div>
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd frontend && bun run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Navigation.jsx
git commit -m "Phase 1b: add Beispiele nav link"
```

---

## Task 6: Styling — `App.css`

**Files:**
- Modify: `frontend/src/App.css`

**Context:** Add classes for the new blocks in the existing visual style, style the Phase-Q leftover classes (`quota-note`, `quick-check-result`, `quick-check-history`), and remove the now-unused `quick-check-cta` rule (the homepage CTA was replaced by the action cards). The page already uses `.home-page`, `.hero-section`, `.hero-title`, `.hero-subtitle`, `.shows-list`, `.show-item`, `.loading-container`, `.loading-spinner`, `.coming-soon-badge`, `.action-button.primary`, `.form-error` — reuse those; only add what's new.

- [ ] **Step 1: Remove the obsolete `quick-check-cta` rule**

Search `frontend/src/App.css` for `.quick-check-cta`:

Run: `grep -n "quick-check-cta" frontend/src/App.css`

Delete the entire CSS rule block(s) matching `.quick-check-cta` (selector + braces). If there are hover/responsive variants (`.quick-check-cta:hover`, etc.), remove those too. (If `grep` returns nothing, the rule was already gone — skip this step.)

- [ ] **Step 2: Append the new styles**

Append to `frontend/src/App.css`:

```css
/* === Phase 1b: Homepage landing === */

.access-unlock {
  max-width: 480px;
  margin: 0 auto 2rem;
}

.access-unlock-form {
  display: flex;
  gap: 0.5rem;
}

.access-unlock-input {
  flex: 1;
  padding: 0.75rem 1rem;
  border: 1px solid var(--border-color, #d0d0d0);
  border-radius: 8px;
  font-size: 1rem;
}

.access-unlock-status {
  text-align: center;
  color: var(--text-muted, #666);
  font-size: 0.95rem;
}

.action-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 1rem;
  max-width: 720px;
  margin: 0 auto 3rem;
}

.action-card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 1.25rem;
  border: 1px solid var(--border-color, #d0d0d0);
  border-radius: 12px;
  background: var(--card-bg, #fff);
  text-decoration: none;
  color: inherit;
  text-align: left;
  font: inherit;
  cursor: pointer;
  transition: border-color 0.15s, transform 0.15s;
}

.action-card:hover {
  border-color: var(--accent-color, #2563eb);
  transform: translateY(-2px);
}

.action-card--locked {
  opacity: 0.55;
  cursor: not-allowed;
}

.action-card--locked:hover {
  border-color: var(--border-color, #d0d0d0);
  transform: none;
}

.action-card-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.action-card-icon {
  font-size: 1.4rem;
}

.action-card-title {
  font-weight: 600;
  font-size: 1.1rem;
}

.action-card-lock {
  margin-left: auto;
}

.beta-tag {
  font-size: 0.7rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  padding: 0.1rem 0.4rem;
  border-radius: 4px;
  background: var(--accent-color, #2563eb);
  color: #fff;
}

.action-card-desc {
  margin: 0;
  font-size: 0.9rem;
  color: var(--text-muted, #666);
}

.examples-section {
  max-width: 720px;
  margin: 0 auto;
  scroll-margin-top: 80px;
}

.examples-title {
  font-size: 1.4rem;
  margin-bottom: 0.25rem;
}

.examples-intro {
  color: var(--text-muted, #666);
  margin-bottom: 1rem;
}

/* === Phase Q leftovers (now styled) === */

.quota-note {
  text-align: center;
  color: var(--text-muted, #666);
  font-size: 0.9rem;
  margin: 1rem 0;
}

.quick-check-result,
.quick-check-history {
  margin-top: 2rem;
}

.quick-check-result h2,
.quick-check-history h2 {
  font-size: 1.2rem;
  margin-bottom: 1rem;
}

/* Stack action cards on narrow screens */
@media (max-width: 600px) {
  .action-cards {
    grid-template-columns: 1fr;
  }
}
```

> **Note:** The `var(--…, fallback)` defaults are safe even if these custom properties aren't defined elsewhere. If `App.css` already defines a design-token palette (check the top of the file for `:root { --… }`), prefer those exact token names over the fallbacks for visual consistency.

- [ ] **Step 3: Verify the build compiles**

Run: `cd frontend && bun run build`
Expected: build succeeds, no CSS errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.css
git commit -m "Phase 1b: style homepage landing + Phase Q leftover classes"
```

---

## Task 7: Manual verification + roadmap update

**Files:**
- Modify: `docs/superpowers/ROADMAP-session-app.md` (mark Phase 1b ✅)

**Context:** No frontend test harness exists, so the homepage is verified by build + manual click-through (spec §Test-Strategie). The backend is already covered by Task 1's tests.

- [ ] **Step 1: Run the full backend unit suite + lint**

Run: `uv run pytest backend/tests -m "not integration" && uv run ruff check backend/`
Expected: all pass, ruff clean.

- [ ] **Step 2: Build the frontend**

Run: `cd frontend && bun run build`
Expected: build succeeds.

- [ ] **Step 3: Manual click-test (dev server)**

Start the frontend dev server (`cd frontend && bun run dev`) and verify, in the browser:
- Fresh load (clear `localStorage` key `fc_access_code` first): action cards show locked (dimmed + 🔒); clicking a card focuses the code input and does **not** navigate.
- Entering an invalid code → "Ungültiger Zugangscode" error, input cleared, cards stay locked.
- Entering a valid code → cards unlock ("Freigeschaltet als …"), both become navigable `<Link>`s.
- Reload after a successful unlock → page renders unlocked immediately (no re-typing).
- "Behauptung prüfen" → `/pruefen`; "Live-Session starten" → `/new` (carries beta tag).
- Examples list renders (flat, no `test` entry), links to `/{session_id}`.
- Nav "Beispiele" link scrolls to the examples section.
- Narrow viewport (≤600px): action cards stack vertically.

- [ ] **Step 4: Mark Phase 1b complete in the roadmap**

In `docs/superpowers/ROADMAP-session-app.md`:
- Line ~44 (the table row): change `| **1b** | Homepage / App-Informationsarchitektur neu denken | ⬜ Offen (eigener Spec) |` → `| **1b** | Homepage / App-Informationsarchitektur neu denken | ✅ Fertig |`.
- Line ~88 (the section heading): change `## ⬜ Phase 1b — Homepage / Informationsarchitektur` → `## ✅ Phase 1b — Homepage / Informationsarchitektur`.

(Confirm exact line numbers with `grep -n "1b" docs/superpowers/ROADMAP-session-app.md` before editing — the table-row and heading are the two `⬜`-marked occurrences.)

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/ROADMAP-session-app.md
git commit -m "Phase 1b: mark complete in roadmap"
```

---

## Self-Review Notes

- **Spec coverage:** Hero (Task 4) · single unlock + `validateCode` (Tasks 2,3,4) · two equal cards w/ beta tag + locked state focusing the field (Task 4) · examples flat list w/ `test` filter (Task 4) · `GET /api/validate-code` side-effect-free w/ public fields only (Task 1) · nav Beispiele link (Task 5) · App.css new + Phase-Q leftover classes, `quick-check-cta` removed (Task 6) · backend tests 200/401/403 + no-leak + side-effect-free (Task 1) · roadmap (Task 7). All spec sections map to a task.
- **Deep-link fallback:** unchanged by design — `/pruefen` and `/new` keep their own code field (no task needed; verified `QuickCheckPage.jsx` already has it).
- **Type consistency:** `validateCode(code)` returns `{ name, quick_check_limit, quick_checks_used }` (Task 1 ↔ Task 2). `AccessUnlock` props `{ unlocked, name, onUnlock }` and `onUnlock(code, name)` signature match between Task 3 and Task 4. `focus()` imperative handle (Task 3) ↔ `unlockRef.current?.focus()` (Task 4).
