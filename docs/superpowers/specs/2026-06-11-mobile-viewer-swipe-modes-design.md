# Mobile-First Viewer with Three Modes — Design

**Date:** 2026-06-11
**Branch:** `worktree-session-multitenancy`
**Status:** Approved, ready for implementation planning

## Summary

Replace the current binary **Admin-Modus ↔ Normal-Modus** experience on the
FactCheckPage with a mobile-first viewer offering three experiences:

- **Swipe** (default) — one claim card at a time; swipe right = fact-check it
  now, swipe left = discard, tap = correct inline then check.
- **Auto** — a header toggle ("Auto-Prüfung"); the operator can put the phone
  down and the backend automatically selects the most relevant claims per audio
  block (`select_async`, ≤3) and checks them.
- **Pro** — the existing `AdminView` power UI (pipeline status, pending/staging,
  bulk actions, editing), reached via a discreet ⚙ entry and gated by today's
  admin condition.

The motivation is that the existing admin workflow (Pending Claims → Staging
Area → "Alle senden", plus the Admin/Normal mode switch) exposes too much jargon
and process for an ordinary app user, who now records their own conversation via
the in-browser microphone recorder. The Pro mode is retained unchanged because it
has real advantages for the operator; it simply stops being the default path.

This builds on the just-completed browser microphone recorder and is part of the
Phase-2+ "multi-user app" direction.

## Decisions (locked)

- **Default screen:** the new **Review view** (Swipe + results feed), *not* the
  old `SpeakerColumns`. Applies to every viewer.
- **Swipe semantics:** right = **approve & fact-check immediately**; left =
  **discard**; tap the card = **inline edit** (speaker + claim text) then check.
  Editing is an optional extra tap, never forced.
- **Card cadence:** exactly **one** claim card visible at a time (no visible
  stack), with a small "noch N" remaining counter.
- **Auto mode:** a header toggle, **off by default**. When on, the swipe card is
  replaced by a calm "Handy kann liegen bleiben" status and the backend
  auto-selects the best claims per block (reusing the existing `select_async`
  selection, ≤3 per block) and checks them.
- **Pro mode:** the **existing `AdminView`**, unchanged. Reached via a discreet
  ⚙ entry shown only when today's admin gate is satisfied. The current
  "Admin-Modus" / "Normal-Modus" button becomes "Pro" / "Zurück".
- **Results surface:** a **vertical results feed** of fact-check cards (newest
  first, with a processing spinner for in-flight checks) replaces the
  desktop-oriented `SpeakerColumns` on the viewer screen.
- **Gating:** keep today's `showAdminMode` condition for the Pro entry. Real
  per-user roles/auth are out of scope (future multi-tenant work).
- **Backend:** one change only — make the auto-check selection a **per-session
  flag** instead of a global env var.

## Architecture

### Surfaces & modes

```
FactCheckPage (/<session_id>)
  ├─ ReviewView   ← new default for everyone
  │    ├─ Header: Titel · [Auto-Prüfung ◯/●] · ⚙ Pro (only if admin gate)
  │    ├─ Swipe area:
  │    │    Auto OFF & pending exist → <SwipeCard> (one claim)
  │    │    Auto OFF & no pending     → "Warte auf Aussagen…"
  │    │    Auto ON                   → "Automatisch — Handy kann liegen bleiben"
  │    └─ Results feed: vertical list of fact-check cards (newest first, ⟳ in-flight)
  └─ AdminView (Pro)   ← existing component, unchanged; entered via ⚙
```

The operator's recording bar (browser mic recorder) remains where it is in the
admin/Pro area; this design does not move it. The ReviewView is what a normal
viewer sees by default.

### Components (frontend)

**`frontend/src/components/SwipeCard.jsx`** (new) — renders a single pending
claim and handles the gesture/interaction:

- Props: `claim` (`{ id, name, claim, ... }`), `remaining` (number),
  `onKeep(editedClaim)`, `onDiscard(claim)`.
- Drag/swipe: horizontal drag past a threshold commits keep (right) or discard
  (left); below threshold it springs back. Buttons ("Verwerfen" / "Behalten")
  provide an accessible, non-gesture path doing the same thing.
- Tap → edit mode: inline editable speaker + claim text fields; a "Prüfen"
  action commits the edited claim via `onKeep`. Edit is optional.
- One card at a time; shows the "noch N" counter from `remaining`.

**`frontend/src/components/ReviewView.jsx`** (new) — the default viewer layout:

- Owns the Auto toggle state (reflecting the session's `auto_check`), the current
  pending-claim cursor, and renders `SwipeCard` (Auto off) or the Auto status.
- Renders the results feed below from fetched fact-checks.
- Wires gestures to API: keep → `approveClaims`, discard → `discardClaims`, then
  advances to the next pending claim. Auto toggle → `setSessionAutoCheck`.

**`frontend/src/components/ResultsFeed.jsx`** (new, or a thin wrapper reusing
`ClaimCard`) — vertical list of fact-check result cards, newest first, with a
processing spinner for entries whose `status === 'processing'`. This replaces
`SpeakerColumns` on the viewer screen (SpeakerColumns is not deleted; it is just
no longer the viewer default).

**`frontend/src/pages/FactCheckPage.jsx`** (modify) — render `ReviewView` as the
default branch; render `AdminView` (Pro) when the ⚙ Pro toggle is active and the
admin gate is satisfied. Relabel the existing mode button to "Pro" / "Zurück".

**`frontend/src/services/api.js`** (modify) — add `setSessionAutoCheck(sessionId,
enabled)` that POSTs to the new endpoint with `authHeaders()`. Reuse the existing
`approveClaims` / `discardClaims` helpers for swipe actions (verify their exact
current signatures during planning; if a single-claim convenience wrapper is
warranted it lives here).

### Data flow

```
mic recorder ─▶ /api/audio-block ─▶ transcription ─▶ claim extraction
                                                        │
                                                        ▼
                                            pending claims (per session)
        ┌───────────────────────────────────────────────┴─────────────┐
   Auto OFF (Swipe)                                              Auto ON
   ReviewView polls /api/pending-claims                  backend pipeline sees
   → shows one SwipeCard                                 session.auto_check → runs
   right → approveClaims([claim]) ─┐                     select_async(≤3) → checks
   left  → discardClaims([claim])  │                              │
   tap   → edit then approve       │                              │
                                   ▼                              ▼
                        fact-check pipeline ─▶ /api/fact-checks (results)
                                   └──────────────┬───────────────┘
                                                  ▼
                                   ReviewView polls fact-checks → ResultsFeed
```

### Backend change (minimal)

Today the auto-check branch in both `backend/routers/audio.py` and
`backend/routers/claims.py` is gated by a global env var:
`os.getenv("AUTO_APPROVE")`. Make it a **per-session flag**:

- Add an `auto_check` boolean to the session (persisted on the session row).
- New endpoint `POST /api/sessions/{session_id}/auto-check` (gated by
  `require_code`) that sets it; body `{ "enabled": true|false }`.
- In the pipeline, replace the bare env check with
  `session.auto_check or os.getenv("AUTO_APPROVE", "false").lower() == "true"`
  so the global env still works for tests/dev but the per-session toggle drives
  the UI. The selection/auto-check logic itself (`select_async(..., max_claims=3)`
  → placeholders → `process_fact_checks_async`) is unchanged.
- `GET /api/sessions/{session_id}` (or `/api/config/{session_id}`) returns the
  current `auto_check` so ReviewView can initialise the toggle. (Confirm which
  read endpoint the viewer already calls during planning and surface the flag
  there.)

All other claim operations reuse existing endpoints:
`GET /api/pending-claims`, `POST /api/approve-claims`, `POST /api/discard-claims`,
`GET /api/fact-checks`.

### Error handling & empty states

- A failed keep/discard call leaves the card in place, shows a brief inline
  message, and lets the next gesture retry. No claim is silently lost.
- A failed Auto-toggle reverts the switch to its prior state with a brief message.
- Empty pending (Auto off): "Warte auf Aussagen…". Empty results: "Noch keine
  Ergebnisse". Auto on: the calm "Handy kann liegen bleiben" status.

## Testing

**Frontend (vitest + @testing-library/react):**
- `SwipeCard`: a right commit calls `onKeep` with the (possibly edited) claim; a
  left commit calls `onDiscard`; a below-threshold drag commits neither; the
  button path mirrors the gestures; edit mode surfaces the edited fields to
  `onKeep`.
- `ReviewView`: keep advances to the next pending claim and calls `approveClaims`;
  discard calls `discardClaims`; toggling Auto calls `setSessionAutoCheck` and
  hides the card; the results feed renders processing (⟳) and done states.
- `api.setSessionAutoCheck`: posts the right body/headers; throws on non-ok.

**Backend (pytest, not integration):**
- The pipeline runs the auto-select branch when a session has `auto_check=true`
  even with the env var unset, and skips it when both are false.
- The `auto-check` endpoint sets the flag and is gated by `require_code`.

**Manual click-test:** on a phone, record a short conversation; in Swipe mode
keep/discard/edit a few claims and confirm results land in the feed; flip Auto on
and confirm claims get checked without interaction; open Pro and confirm the
existing admin UI still works.

## Out of scope (YAGNI)

- Undo of a committed swipe.
- Elaborate animations or a visible card-stack effect.
- Real per-user roles / authentication (Pro stays behind today's gate condition).
- Desktop-specific layout polish for the viewer (mobile-first; desktop is
  acceptable, not optimised).
- Deleting `SpeakerColumns` (kept; just not the viewer default).

## Risks / notes

- **Claims arriving faster than the user swipes** during a live conversation:
  handled by the "noch N" counter and the always-available Auto toggle (put the
  phone down). No queue cap in this scope.
- **`approveClaims` / `discardClaims` current signatures** may be batch-oriented;
  planning must confirm them and adapt the single-claim swipe wiring (a thin
  wrapper is fine, no endpoint change).
- **Per-session `auto_check` persistence** rides on the existing session
  storage; confirm the session schema/`Episode.from_session_row` path during
  planning so the flag round-trips.
- **Single-process backend state** is unchanged; one session's auto_check does
  not affect others.
