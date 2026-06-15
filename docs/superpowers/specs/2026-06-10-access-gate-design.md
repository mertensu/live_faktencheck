# Spec — Minimal Access Gate (Phase 3a)

**Date:** 2026-06-10
**Branch:** `worktree-session-multitenancy` (Worktree: `.claude/worktrees/session-multitenancy`)
**Status:** Designed — ready for implementation plan.

## Problem

Since the Phase 4 VPS cutover, `https://api.live-faktencheck.de` is reachable by anyone
on the internet **with no credential**. Endpoints that trigger paid external API calls —
`POST /api/sessions`, `POST /api/audio-block`, claim/fact-check triggers — can be invoked
by any script or bot, spending real money on the AssemblyAI / Gemini / Tavily keys. The
CORS regex in `backend/app.py` does **not** protect against this: CORS is browser-enforced
and ignored by `curl`/scripts. The blast radius is the metered API bills.

This spec closes that hole with the smallest change that works: a server-side access-code
gate on the cost-incurring endpoints, plus a documented manual step to set provider-side
budget caps.

## Scope

**In scope (this pass):**
- A SQLite `codes` table with named per-person codes, seeded from an env var (fail-closed).
- A `require_code` FastAPI dependency validating an `X-Access-Code` header.
- Gating every endpoint that can trigger a paid external API call or create a session.
- Writing the validated code to the existing `owner_code` column on session creation.
- Minimal frontend: a code field on the `/new` create flow, header attachment, and
  401/403 handling.
- A documented runbook step for provider-side budget caps (not code).

**Explicitly out of scope (deferred to their own designs):**
- Quick Check (one-shot text quote → fact-check) feature.
- 10-minute live-session auto-stop.
- Global daily circuit breaker / per-code quotas.
- Admin UI for managing codes (managed via DB/seed for now).
- Protecting the integrity of an *already-known* session id (see Non-goals).

## Background — what already exists (Phase 1)

- `sessions` table already has an `owner_code TEXT` column (created, never populated yet).
- `owner_code` is already filtered out of the `/api/config/{session_id}` response — no leak.
- Sessions are private-by-link: `session_id` is a random 12-hex string and acts as the
  capability for reading a session.
- Legacy `EPISODES` are seeded as **public** sessions at startup (internal, not via the
  gated API) and remain readable without a code.

## Design

### 1. Data model — `codes` table

```sql
CREATE TABLE IF NOT EXISTS codes (
  code        TEXT PRIMARY KEY,
  name        TEXT NOT NULL,        -- owner of the code (e.g. "ulf", "anna")
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL
);
```

Added to the schema-creation block in `backend/database.py` (same place as the `sessions`
table). No migration needed for existing DBs beyond `CREATE TABLE IF NOT EXISTS`.

**Seeding (fail-closed):** at startup, if the `codes` table is empty, parse the
`ACCESS_CODES` env var and insert one row per entry.
- Format: `ACCESS_CODES=ulf:secret1,anna:secret2` (comma-separated `name:code` pairs).
- If `ACCESS_CODES` is unset/empty **and** the table is empty, the table stays empty and
  **every gated endpoint denies all requests**. The backend is safe by default; seeding a
  code is a required deploy step. This is intentional — an unconfigured deploy must not be
  open.
- Seeding is idempotent: it only runs when the table is empty, so editing `ACCESS_CODES`
  later and restarting does **not** silently re-add revoked codes. Adding/removing codes
  after first seed is done via DB (see "Managing codes").

**New DB methods** (`backend/database.py`):
- `get_code(code: str) -> dict | None` — returns the row only if `active = 1`.
- `add_code(code: str, name: str)` — insert (used by seeding).
- `deactivate_code(code: str) -> bool` — set `active = 0`.
- `list_codes() -> list[dict]` — for inspection/management.

### 2. Validation — `require_code` dependency

New module `backend/auth.py`:

```python
from fastapi import Header, HTTPException
import backend.state as state

async def require_code(x_access_code: str | None = Header(default=None)) -> dict:
    if not x_access_code:
        raise HTTPException(status_code=401, detail="Zugangscode erforderlich")
    row = await state.get_db().get_code(x_access_code)
    if row is None:
        raise HTTPException(status_code=403, detail="Zugangscode ungültig")
    return row
```

- Missing header → **401** (`Zugangscode erforderlich`).
- Unknown or inactive code → **403** (`Zugangscode ungültig`).
- Valid → returns the code row (`{code, name, active, created_at}`).

Applied to endpoints via `Depends(require_code)`. On `POST /api/sessions`, the validated
**code** value is written to the new session's `owner_code` column (the `name` stays
recoverable via a join on the `codes` table for attribution).

### 3. Gating rule

**Gate every endpoint that can trigger a paid external API call or create a session.**

| Endpoint | Why gated |
|----------|-----------|
| `POST /api/sessions` | creates a session; sets `owner_code` |
| `POST /api/audio-block` | AssemblyAI transcription + Gemini extraction |
| `POST /api/text-block` | Gemini claim extraction |
| `POST /api/approve-claims` | Gemini + Tavily fact-checking |
| `POST /api/fact-checks/resend` | re-runs fact-checking |
| `POST /api/pipeline/*` retrigger | re-runs the pipeline |

**Left open (no code required):**
- All `GET`s (`/api/config/*`, `/api/fact-checks`, `/api/trusted-domains`,
  `/api/sessions/{id}`, `/api/health`) — they cost nothing and shared private links must
  keep working without a code.
- Non-paid mutations: `POST /api/sessions/{id}/end`, `DELETE /api/pending-claims/{id}` —
  they spend no money; the random session id is the capability.

### 4. Frontend (minimal)

- `frontend/src/services/api.js`:
  - `getAccessCode()` / `setAccessCode(code)` backed by `localStorage`.
  - Attach `X-Access-Code: <code>` header to requests when a code is present (harmless on
    GETs, required on gated POSTs).
  - On a `401`/`403` from a gated call, clear/flag the stored code and surface a re-entry
    prompt rather than a generic error.
- `/new` create-session flow: a single **Zugangscode** input field. On submit, persist via
  `setAccessCode` and send the header with the create request. If the create call returns
  401/403, show "Zugangscode erforderlich/ungültig" and keep the user on the form.
- Shared read-only link views (`/{session_id}`) are unchanged — no code needed to view.

No separate login page; the code lives with the create flow.

### 5. Provider budget caps (manual runbook — not code)

Add a short section to `docs/deployment.md` (or a new `docs/security.md`) documenting the
outer ceiling that holds even if a code leaks:
- AssemblyAI: set a spend/usage cap + alert in the dashboard.
- Google/Gemini (AI Studio / Cloud billing): set a budget + alert.
- Tavily: set a usage cap/alert.
This is an operational step the operator performs once; it is not enforced in code.

## Non-goals

- **Integrity of an already-known session id.** A party who already holds a valid
  `session_id` (e.g. someone the link was shared with) can call the open, non-paid
  mutations (`end`, delete pending block) on it. This is acceptable: the scope here is
  *cost*, ids are unguessable (random 12-hex), and the capability-URL model is the existing
  Phase 1 design. Tightening this would belong to a later, separate hardening pass.
- Per-user quotas, rate limiting, auto-stop, circuit breaker — deferred (see Scope).

## Testing

- **`require_code`:** missing header → 401; unknown code → 403; inactive code → 403; valid
  code → returns row with the expected `name`.
- **DB:** env-seed inserts the expected codes; seed is idempotent (no-op when table
  non-empty); `get_code` returns only `active` rows; `deactivate_code` flips `active`.
- **Endpoints:** a gated endpoint without a code → 401; with a valid code → succeeds and
  (for `POST /api/sessions`) persists `owner_code`; representative `GET`s succeed **without**
  a code.
- **Regression:** the existing two-session isolation test stays green; legacy public
  sessions remain readable without a code.

## Managing codes (operational)

- **Add a tester:** add `name:code` to `ACCESS_CODES` and either (re)seed into a fresh DB
  or insert directly via `add_code` / SQL on the running DB.
- **Revoke a tester:** `deactivate_code(code)` (or `UPDATE codes SET active=0 WHERE code=?`)
  — takes effect immediately, no restart.
- An admin UI is intentionally deferred; a handful of codes are managed by DB/SQL for now.

## Configuration

- `ACCESS_CODES` env var in `.env` (gitignored) on the VPS — required for the app to
  function (fail-closed otherwise). Documented in `docs/deployment.md`.
