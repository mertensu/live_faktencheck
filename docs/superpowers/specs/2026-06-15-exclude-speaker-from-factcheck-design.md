# Design: Exclude a speaker from fact-checking

**Date:** 2026-06-15
**Status:** Approved (ready for implementation plan)

## Problem

In every conversation type there are speakers whose statements are not worth
fact-checking: the **moderator** in a talk-show/debate, the **interviewer** in an
interview, or **oneself** in a private conversation. Today the pipeline extracts
and checks claims from everyone. The user wants the ability to flag specific
speakers so their statements are never fact-checked.

## Goals

- Let the session creator mark one or more participants as "don't check".
- Skip those speakers' statements at extraction time (cheapest — no fact-check
  calls are spent on them).
- Available for **all** conversation types (`debate`, `interview`, `private`).
- Fully backward-compatible: when nothing is flagged, behaviour is unchanged.

## Non-goals

- Per-claim speaker attribution. Claims remain `{claim: str}` with no speaker
  field; we only need to know *who to ignore*, not who said each kept claim.
- A hard, deterministic guarantee that an excluded speaker's claim never slips
  through. v1 relies on the LLM honouring the prompt instruction (see Risks).
- Editing exclusions after a session is created (set once in the wizard).

## Approach

The transcript is already speaker-resolved to real names *before* claim
extraction (`resolve_labels_async` → `extract_claims_async`). So the extractor
can be instructed, by name, to skip statements from the excluded people. No new
attribution machinery is required.

### 1. Data model & UI (frontend `frontend/src/wizard/`)

- Each wizard person gains a boolean field `exclude` (alongside `name`, `party`,
  `role`). `emptyPerson()` initialises it to `false`.
- The "people" step renders a checkbox per participant labelled
  **"Aussagen nicht prüfen"**, shown for all conversation types.
- `buildSessionPayload` derives `excluded_speakers: string[]` — the trimmed
  `name` of every person whose `exclude` is `true` and whose name is non-empty.
- **Validation:** a person with `exclude === true` but an empty `name` makes the
  people step invalid (the extractor identifies excluded speakers by name).
  `peopleStepValid` is extended to enforce this for every conversation type.

### 2. Session persistence (backend)

- `SessionCreate` and the session response model in `backend/models.py` gain
  `excluded_speakers: list[str] = []`.
- `backend/database.py`: add an `excluded_speakers` column (stored like `guests`,
  e.g. JSON-encoded text), included in insert/select and round-tripped in the
  session dict. Migration follows the existing column-add pattern in this file.
- `backend/routers/sessions.py`: accept and return the field; default `[]`.

### 3. Enforcement (extraction)

- `ClaimExtractionInput` (`backend/services/claim_extraction.py`) gains
  `excluded_speakers: list[str] = []` with a German `Field` description.
- The audio pipeline (`backend/routers/audio.py`) and any text-block path pass
  the session's `excluded_speakers` into `extract_claims_async` / `extract_async`
  (new keyword arg, default `[]`, threaded through like `conversation_type`).
- `prompts/claim_extraction.md` gains a rule: *if `excluded_speakers` is
  non-empty, do not extract any claim made by those people; skip their statements
  entirely.* Matching is by the resolved real name.
- Speaker-label resolution (`speaker_labels.md`, `resolve_labels_async`) is
  untouched.

## Data flow

```
Wizard people [{name, party, role, exclude}]
  -> buildSessionPayload -> excluded_speakers: ["Caren Miosga"]
  -> POST /api/sessions (persisted)
  -> audio/text pipeline reads session.excluded_speakers
  -> resolve_labels_async (unchanged) -> resolved transcript
  -> extract_claims_async(..., excluded_speakers=[...])
  -> ClaimExtractionInput -> prompt skips those speakers
  -> claims (excluded speakers absent)
```

## Testing

- `frontend/src/wizard/wizardLogic.test.js`:
  - `buildSessionPayload` emits `excluded_speakers` from checked, named people.
  - Unchecked / unnamed people produce no entries.
  - `peopleStepValid` is false when a person is `exclude`-checked but unnamed.
- Backend unit tests:
  - Session create/read round-trips `excluded_speakers` (DB + router).
  - `excluded_speakers` reaches `ClaimExtractionInput` through the pipeline.
- Integration test (marked `integration`): short transcript where an excluded
  speaker makes an obvious factual claim → assert it is absent from extracted
  claims; a non-excluded speaker's claim is present.

## Backward compatibility

- Empty `excluded_speakers` (the default and the value for all existing sessions)
  changes nothing in extraction or the prompt.
- New DB column defaults to an empty list for existing rows.

## Risks & limitations

- **Soft enforcement.** The skip relies on the LLM following the prompt; it may
  occasionally extract an excluded speaker's claim. Accepted for v1. A future
  hardening could add per-claim speaker attribution and a deterministic filter.
- **Name matching.** Exclusion keys on the resolved name; if the resolver fails
  to map a label to that name, the speaker won't be recognised as excluded. This
  shares the existing dependency on speaker-label resolution quality.
