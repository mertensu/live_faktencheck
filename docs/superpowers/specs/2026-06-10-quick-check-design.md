# Phase Q — Quick Check: Design

**Date:** 2026-06-10
**Branch:** `worktree-session-multitenancy`
**Status:** Spec approved, awaiting plan.

## Goal

A low-friction entry point to the product: a user pastes a single **text quote**
and gets it fact-checked directly through the existing `fact_checker` service
(Gemini + Tavily) — no audio, no transcription, no claim extraction. Independent
of Phase 2 (browser audio); the fastest path to a usable product.

Depends on Phase 3a (access-code gate), which is already live.

## Scope

**In scope:**
- A synchronous `POST /api/quick-check` endpoint, code-gated like 3a.
- A per-code lifetime quota of **3 quick checks** (owner code exempt).
- A dedicated Quick Check screen (`/pruefen`): claim input + result + history.
- Persistence so results are revisitable after closing the app.

**Deliberately out of scope:**
- Background processing / polling (one claim, user waits on screen → synchronous).
- The two-button homepage redesign (Phase 1b).
- Live-session limits / auto-stop (Phase 3b).
- Editing or resending quick-check results.
- Speaker / context / date input fields (claim text only).

## Architecture & Flow

```
[/pruefen page]  POST /api/quick-check  { claim }   + X-Access-Code header
        │
        ├─ require_code        → 401 (no header) / 403 (invalid or inactive)
        ├─ quota check (codes) → 429 "Kontingent aufgebraucht" (owner exempt)
        ├─ fact_checker.check_claim_async(speaker="", claim, episode_date=<heute>)
        ├─ build_fact_check_dict(result, session_id="quick-<code>") → add_fact_check
        ├─ increment codes.quick_checks_used
        └─ 200 { fact_check }   → rendered in ClaimCard
```

Synchronous: the live pipeline uses background tasks + polling because it processes
many claims from audio blocks. Quick Check is a single claim with the user waiting,
so the endpoint awaits `check_claim_async` and returns the result directly. The real
check takes ~10–30s; the Cloudflare tunnel's request timeout (well above that) is fine.

On page load with a valid code entered, the page also calls
`GET /api/fact-checks?session_id=quick-<code>` to show that code's past quick checks
(revisitable after closing the app). That GET endpoint is already open (ungated),
consistent with the shared-private-link trust model from Phase 3a.

## Backend

- **New router** `backend/routers/quick_check.py` registered in `app.py`.
  - `POST /api/quick-check` with `Depends(require_code)`.
- **Request model** `QuickCheckRequest { claim: str }`:
  - non-empty after strip; max ~1000 chars (cost / abuse guard).
  - validation failure → `422` **before** any LLM call (no quota spent).
- **Reuses** `FactChecker.check_claim_async(speaker, claim, context=None, episode_date=None)`
  with `speaker=""`, no context, and `episode_date` = current month + year
  (e.g. `"Juni 2026"`), matching the `sendedatum` format the checker expects.
- **Reuses** the existing `build_fact_check_dict(result, session_id)` helper and
  `db.add_fact_check(...)` for persistence.
- **Quota** is enforced in the router using new DB methods (below). The counter is
  incremented only on a successful (HTTP 200) check.

## Data Model

Additive migrations on the existing `codes` table, using the same `ALTER TABLE ...`
migration pattern already present in `database.py`:

- `quick_checks_used  INTEGER NOT NULL DEFAULT 0`
- `quick_check_limit   INTEGER` — `NULL` = unlimited (owner); otherwise the cap.
  New rows seeded with `3` unless the seed specifies otherwise.

The lifetime quota is tracked by the `quick_checks_used` counter on `codes`, **not**
by counting `fact_checks` rows — so deleting a quick-check row does not refund quota.

### Seeding syntax

Extend `ACCESS_CODES` to an optional third field per entry: `name:code:limit`.
- `name:code` → limit defaults to `3`.
- `name:code:unlimited` → `quick_check_limit = NULL` (no cap).
- `name:code:<n>` → `quick_check_limit = <n>`.

Example: `ACCESS_CODES=ulfkai:0311:unlimited` gives the owner code an unbounded quota;
any additional code without a third field defaults to 3.

`parse_access_codes` is extended to parse the optional third field; `seed_codes_from_env`
sets `quick_check_limit` accordingly. Seeding stays idempotent and fail-closed.

### New DB methods

- `get_quick_check_quota(code) -> {used, limit}` (or equivalent) — reads the two columns.
- `increment_quick_checks(code)` — atomically bumps `quick_checks_used` by 1.

## Frontend (Quick Check screen only)

- **New route** `/pruefen` → `QuickCheckPage.jsx`.
- Access-code field, reusing `getAccessCode` / `setAccessCode` / `authHeaders()` from
  `services/api.js` (same mechanism as the `/new` live-session form).
- Claim `<textarea>` + submit button.
- On submit: show a spinner during the ~10–30s check, then render the returned
  fact-check with the **existing `ClaimCard`** component.
- Show remaining quota ("noch X von 3 übrig"); for an unlimited code, omit/soften it.
- Below the form, list the code's past quick checks (from the history GET).
- The existing homepage gets a link to `/pruefen`. The full two-button
  (Quick Check + Live) homepage redesign is deferred to Phase 1b.

## Error Handling

- `401` — no `X-Access-Code` header.
- `403` — unknown or inactive code.
- `429` — quota exhausted (owner code with `NULL` limit never hits this).
- `422` — empty or oversized claim; raised before any LLM call, no quota spent.
- Checker exception — `check_claim_async` already returns a safe fallback dict
  (`consistency: "unklar"`); the result is still persisted and the quota is still
  counted, because the (paid) API call was incurred.
- All user-facing messages are German, shown inline on the page.

## Testing (TDD)

Unit (mocked checker via the existing `mock_fact_checker` / `TestModel` fixtures;
`models.ALLOW_MODEL_REQUESTS=False`):
- Happy path: persists a `fact_checks` row under `quick-<code>`, increments
  `quick_checks_used`, returns the fact-check.
- Quota exhausted (`used >= limit`) → `429`, no new row, no increment.
- Owner code (`quick_check_limit IS NULL`) → never blocked regardless of `used`.
- No code → `401`; invalid/inactive code → `403`.
- Empty / whitespace-only / oversized claim → `422`, no LLM call, no increment.

DB tests:
- The two new columns exist after migration on a pre-existing `codes` table.
- `get_quick_check_quota` / `increment_quick_checks` behave correctly.

Parsing test:
- `parse_access_codes` handles the optional third field (`unlimited`, a number,
  and absent → default 3).

## Out-of-Scope Confirmations

Background processing/polling, the two-button homepage (Phase 1b), live-session
limits (Phase 3b), and editing/resending quick-check results are explicitly excluded.
