# Live-Audio-Limits (Phase 3b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cap live-audio cost per access code by metering real transcribed audio seconds (lifetime, fail-closed), enforced on `POST /api/audio-block`.

**Architecture:** Mirror the existing Quick-Check quota pattern. Two new columns on the `codes` table (`audio_seconds_used`, `audio_seconds_limit`) track a lifetime budget. The `require_code`-gated handler runs two pre-call guards (budget → 429, block size → 413) before any paid transcription, returns `remaining_seconds`, and threads the code into the background pipeline, which increments the counter by the real `audio_duration` AssemblyAI returns. The frontend stops the recorder on 429 and shows a "remaining" countdown in the recording bar.

**Tech Stack:** FastAPI + aiosqlite (backend), AssemblyAI SDK (`transcript.audio_duration`), React hooks + Vite (frontend), pytest + Vitest.

**Spec:** `docs/superpowers/specs/2026-06-12-live-audio-limits-design.md`

**Conventions:**
- Run Python with `uv run pytest ...`. Lint with `uv run ruff check backend/`.
- Frontend tests: `cd frontend && bun run test`. Build: `cd frontend && bun run build`.
- Commit after each task with a short one-line message (no co-author trailer).

---

## File Structure

**Backend**
- `backend/database.py` — Modify: add the two columns to the `codes` CREATE + idempotent ALTER migrations; add `audio_seconds_limit` param to `add_code`; add `increment_audio_seconds()`.
- `backend/auth.py` — Modify: add `LIVE_AUDIO_LIMIT_MINUTES` env helper; seed `audio_seconds_limit` (None for unlimited codes, env-derived seconds otherwise). `parse_access_codes` is unchanged.
- `backend/services/transcription.py` — Modify: `transcribe()` and `transcribe_file()` return `(formatted: str, audio_duration: float)`.
- `backend/models.py` — Modify: add `remaining_seconds` to `ProcessingResponse`.
- `backend/routers/audio.py` — Modify: handler pre-call guards (429/413) + `remaining_seconds`; thread `code` into background task; unpack transcribe tuple + `increment_audio_seconds`.

**Backend tests**
- `backend/tests/test_live_audio_limits.py` — Create: DB columns/increment, seeding, endpoint guards.
- `backend/tests/test_audio_pipeline.py` — Modify: update 4 `transcribe` mocks to return `(str, float)`; assert increment.
- `backend/tests/test_transcription.py` — Modify: fake transcript gains `audio_duration`/utterances; assert tuple return.

**Frontend**
- `frontend/src/services/api.js` — Modify: `sendAudioBlock` flags 429 as a quota error; returns `remaining_seconds`.
- `frontend/src/hooks/useAudioRecorder.js` — Modify: track `remainingSeconds`; on quota error stop + message.
- `frontend/src/components/RecordingBar.jsx` — Modify: show "noch M:SS übrig".

**Frontend tests**
- `frontend/src/services/api.test.js` — Modify: quota-error + remaining assertions.
- `frontend/src/hooks/useAudioRecorder.test.js` — Modify: quota-stop behavior.

**Docs**
- `docs/deployment.md` — Modify: `LIVE_AUDIO_LIMIT_MINUTES` env + unlimited-owner runbook note.

---

## Task 1: DB columns, migrations, and increment

**Files:**
- Modify: `backend/database.py` (codes CREATE ~line 98-105; codes migrations ~line 121-130; `add_code` ~line 362-373; add `increment_audio_seconds` after `increment_quick_checks` ~line 408)
- Test: `backend/tests/test_live_audio_limits.py` (create)

- [ ] **Step 1: Write the failing DB tests**

Create `backend/tests/test_live_audio_limits.py`:

```python
"""Tests for Live-Audio-Limits (Phase 3b): per-code audio-seconds budget."""

import pytest

from backend.database import Database


@pytest.fixture
async def fresh_db():
    db = Database(":memory:")
    await db.connect()
    yield db
    await db.close()


# --- DB layer: codes audio columns ---

async def test_add_code_sets_default_audio_limit(fresh_db):
    await fresh_db.add_code("c1", "ann")
    row = await fresh_db.get_code("c1")
    assert row["audio_seconds_used"] == 0
    assert row["audio_seconds_limit"] == 300


async def test_add_code_accepts_explicit_audio_limit(fresh_db):
    await fresh_db.add_code("c2", "max", audio_seconds_limit=600)
    assert (await fresh_db.get_code("c2"))["audio_seconds_limit"] == 600


async def test_add_code_audio_limit_none_is_unlimited(fresh_db):
    await fresh_db.add_code("c3", "owner", audio_seconds_limit=None)
    assert (await fresh_db.get_code("c3"))["audio_seconds_limit"] is None


async def test_increment_audio_seconds_accumulates(fresh_db):
    await fresh_db.add_code("c4", "ann")
    await fresh_db.increment_audio_seconds("c4", 42)
    await fresh_db.increment_audio_seconds("c4", 8)
    assert (await fresh_db.get_code("c4"))["audio_seconds_used"] == 50
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest backend/tests/test_live_audio_limits.py -v`
Expected: FAIL — `add_code()` has no `audio_seconds_limit` kwarg / no `increment_audio_seconds` / KeyError on `audio_seconds_used`.

- [ ] **Step 3: Add the columns to the codes CREATE statement**

In `backend/database.py`, change the `codes` table definition (currently ending at `quick_check_limit INTEGER DEFAULT 3`):

```python
            CREATE TABLE IF NOT EXISTS codes (
                code                TEXT PRIMARY KEY,
                name                TEXT NOT NULL,
                active              INTEGER NOT NULL DEFAULT 1,
                created_at          TEXT NOT NULL,
                quick_checks_used   INTEGER NOT NULL DEFAULT 0,
                quick_check_limit   INTEGER DEFAULT 3,
                audio_seconds_used  INTEGER NOT NULL DEFAULT 0,
                audio_seconds_limit INTEGER DEFAULT 300
            );
```

- [ ] **Step 4: Add idempotent migrations for existing tables**

In `backend/database.py`, right after the existing Quick-Check migration block (the loop with `ALTER TABLE codes ADD COLUMN quick_checks_used ...`), add:

```python
        # Migration: add Live-Audio quota columns to existing codes tables.
        # DEFAULT 300 backfills existing codes to 5 min (fail-closed) — NOT NULL/unlimited.
        for migration in [
            "ALTER TABLE codes ADD COLUMN audio_seconds_used INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE codes ADD COLUMN audio_seconds_limit INTEGER DEFAULT 300",
        ]:
            try:
                await self.db.execute(migration)
                await self.db.commit()
            except Exception:
                pass  # Column already exists
```

- [ ] **Step 5: Extend `add_code` and add `increment_audio_seconds`**

In `backend/database.py`, replace `add_code` with:

```python
    async def add_code(
        self,
        code: str,
        name: str,
        quick_check_limit: int | None = 3,
        audio_seconds_limit: int | None = 300,
    ) -> None:
        """Insert an access code (no-op if the code already exists).

        quick_check_limit: lifetime Quick Check cap; None means unlimited.
        audio_seconds_limit: lifetime live-audio cap in seconds; None means unlimited.
        """
        from datetime import datetime
        await self.db.execute(
            "INSERT OR IGNORE INTO codes "
            "(code, name, active, created_at, quick_check_limit, audio_seconds_limit) "
            "VALUES (?, ?, 1, ?, ?, ?)",
            (code, name, datetime.now().isoformat(), quick_check_limit, audio_seconds_limit),
        )
        await self.db.commit()
```

Then add, directly after `increment_quick_checks`:

```python
    async def increment_audio_seconds(self, code: str, seconds: int) -> None:
        """Add transcribed audio seconds to a code's lifetime counter."""
        await self.db.execute(
            "UPDATE codes SET audio_seconds_used = audio_seconds_used + ? WHERE code = ?",
            (seconds, code),
        )
        await self.db.commit()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest backend/tests/test_live_audio_limits.py -v`
Expected: PASS (4 passed).

- [ ] **Step 7: Run the existing gate tests to confirm no regression**

Run: `uv run pytest backend/tests/test_access_gate.py -v`
Expected: PASS (the `add_code` default path is unchanged for callers that omit the new kwarg).

- [ ] **Step 8: Commit**

```bash
git add backend/database.py backend/tests/test_live_audio_limits.py
git commit -m "feat(db): per-code audio-seconds budget columns + increment"
```

---

## Task 2: Seed the audio limit from env

**Files:**
- Modify: `backend/auth.py` (top-level constants ~line 14; `seed_codes_from_env` ~line 49-62)
- Test: `backend/tests/test_live_audio_limits.py` (append)

- [ ] **Step 1: Write the failing seeding tests**

Append to `backend/tests/test_live_audio_limits.py`:

```python
# --- Env-derived seeding ---

from backend.auth import live_audio_limit_seconds, seed_codes_from_env


def test_live_audio_limit_seconds_default(monkeypatch):
    monkeypatch.delenv("LIVE_AUDIO_LIMIT_MINUTES", raising=False)
    assert live_audio_limit_seconds() == 300


def test_live_audio_limit_seconds_from_env(monkeypatch):
    monkeypatch.setenv("LIVE_AUDIO_LIMIT_MINUTES", "10")
    assert live_audio_limit_seconds() == 600


async def test_seed_sets_audio_limit_from_env(fresh_db, monkeypatch):
    monkeypatch.setenv("LIVE_AUDIO_LIMIT_MINUTES", "2")
    await seed_codes_from_env(fresh_db, "ann:s1")
    assert (await fresh_db.get_code("s1"))["audio_seconds_limit"] == 120


async def test_seed_unlimited_code_has_null_audio_limit(fresh_db, monkeypatch):
    monkeypatch.setenv("LIVE_AUDIO_LIMIT_MINUTES", "5")
    await seed_codes_from_env(fresh_db, "owner:o1:unlimited")
    row = await fresh_db.get_code("o1")
    assert row["quick_check_limit"] is None
    assert row["audio_seconds_limit"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest backend/tests/test_live_audio_limits.py -v -k "audio_limit or seed"`
Expected: FAIL — `cannot import name 'live_audio_limit_seconds'`.

- [ ] **Step 3: Add the env helper to `backend/auth.py`**

Below `DEFAULT_QUICK_CHECK_LIMIT = 3`, add:

```python
DEFAULT_LIVE_AUDIO_LIMIT_MINUTES = 5


def live_audio_limit_seconds() -> int:
    """Lifetime live-audio cap in seconds, from ``LIVE_AUDIO_LIMIT_MINUTES`` (default 5)."""
    raw = os.getenv("LIVE_AUDIO_LIMIT_MINUTES")
    minutes = int(raw) if raw and raw.isdigit() else DEFAULT_LIVE_AUDIO_LIMIT_MINUTES
    return minutes * 60
```

- [ ] **Step 4: Wire the audio limit into `seed_codes_from_env`**

In `backend/auth.py`, replace the seeding loop body so the audio limit follows the unlimited heuristic (`quick_check_limit is None` → unlimited audio too):

```python
    entries = parse_access_codes(raw)
    audio_limit = live_audio_limit_seconds()
    for name, code, limit in entries:
        await db.add_code(
            code,
            name,
            quick_check_limit=limit,
            audio_seconds_limit=None if limit is None else audio_limit,
        )
    return len(entries)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest backend/tests/test_live_audio_limits.py -v`
Expected: PASS (all live-audio tests).

- [ ] **Step 6: Run the gate tests (seeding regression)**

Run: `uv run pytest backend/tests/test_access_gate.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/auth.py backend/tests/test_live_audio_limits.py
git commit -m "feat(auth): seed per-code audio limit from LIVE_AUDIO_LIMIT_MINUTES"
```

---

## Task 3: Transcription returns `(text, audio_duration)`

**Files:**
- Modify: `backend/services/transcription.py` (`transcribe` ~line 81-103; `transcribe_file` ~line 105-120)
- Test: `backend/tests/test_transcription.py`

- [ ] **Step 1: Read the existing transcription test to update its fake**

Run: `uv run pytest backend/tests/test_transcription.py -v`
Expected (current): PASS. Open the file and note the fake `Transcriber.transcribe` returns an object whose `audio_duration` and `utterances` you must define so the new code path works.

- [ ] **Step 2: Update the fake transcript + add a return-shape assertion**

In `backend/tests/test_transcription.py`, ensure the fake transcript object the stub returns carries the fields the formatter + duration read. In the fake `transcribe` method, return an object such as:

```python
class _FakeTranscript:
    status = "completed"
    error = None
    text = "hallo welt"
    utterances = None          # exercise the no-utterances fallback
    audio_duration = 12.5
```

Make the stub `transcribe(self, audio, config=None)` capture the config (as today) and return `_FakeTranscript()`. Then add a test:

```python
def test_transcribe_returns_text_and_duration():
    svc, captured = _make_service()   # use the file's existing service factory
    text, duration = svc.transcribe(b"audio")
    assert text == "hallo welt"
    assert duration == 12.5
```

> Note: adapt `_make_service()` / `captured` to the exact helper names already in the file (around line 38-47). The existing config-assertion tests stay, but each now unpacks `text, _ = svc.transcribe(...)` if it inspects the return; if they only read `captured`, leave them.

- [ ] **Step 3: Run to verify the new test fails**

Run: `uv run pytest backend/tests/test_transcription.py::test_transcribe_returns_text_and_duration -v`
Expected: FAIL — `transcribe` returns a `str`, so tuple-unpack raises `ValueError: too many values to unpack` or `TypeError`.

- [ ] **Step 4: Change `transcribe` and `transcribe_file` signatures**

In `backend/services/transcription.py`, replace the `transcribe` return section:

```python
    def transcribe(self, audio_data: bytes, keyterms: list[str] | None = None) -> tuple[str, float]:
        """Transcribe audio and return (formatted transcript, audio_duration_seconds).

        audio_duration is AssemblyAI's measured length of the submitted audio
        (0.0 if the SDK reports none); used to meter the per-code audio budget.
        """
        logger.info(f"Starting transcription of {len(audio_data)} bytes ({len(keyterms or [])} keyterms)")

        transcript = aai.Transcriber().transcribe(audio_data, self._build_config(keyterms))
        self._raise_on_error(transcript)

        formatted = self._format_transcript(transcript)
        duration = float(transcript.audio_duration or 0.0)
        logger.info(f"Transcription completed: {len(formatted)} characters, {duration:.1f}s audio")
        return formatted, duration
```

And `transcribe_file`:

```python
    def transcribe_file(self, file_path: str, keyterms: list[str] | None = None) -> tuple[str, float]:
        """Transcribe audio from a file path. Returns (formatted transcript, audio_duration_seconds)."""
        logger.info(f"Transcribing file: {file_path}")

        transcript = aai.Transcriber().transcribe(file_path, self._build_config(keyterms))
        self._raise_on_error(transcript)
        return self._format_transcript(transcript), float(transcript.audio_duration or 0.0)
```

- [ ] **Step 5: Run the transcription tests to verify they pass**

Run: `uv run pytest backend/tests/test_transcription.py -v`
Expected: PASS (including the new duration test).

- [ ] **Step 6: Commit**

```bash
git add backend/services/transcription.py backend/tests/test_transcription.py
git commit -m "feat(transcription): return (text, audio_duration) tuple"
```

---

## Task 4: Handler guards (429/413) + `remaining_seconds` + thread code

**Files:**
- Modify: `backend/models.py` (`ProcessingResponse` ~line 98-105)
- Modify: `backend/routers/audio.py` (imports ~line 11-21; module constant near `AUDIO_TMP_DIR` ~line 27; `receive_audio_block` ~line 50-95)
- Test: `backend/tests/test_live_audio_limits.py` (append endpoint tests)

- [ ] **Step 1: Write the failing endpoint guard tests**

Append to `backend/tests/test_live_audio_limits.py`:

```python
# --- Endpoint guards on POST /api/audio-block ---

from unittest.mock import AsyncMock, MagicMock, patch

import backend.state as state
from backend.tests.conftest import TEST_ACCESS_CODE


def _audio_form():
    return {"audio": ("block.webm", b"x" * 1000, "audio/webm")}, {"session_id": "s-ep"}


async def _set_code_budget(used: int, limit):
    await state.db.db.execute(
        "UPDATE codes SET audio_seconds_used = ?, audio_seconds_limit = ? WHERE code = ?",
        (used, limit, TEST_ACCESS_CODE),
    )
    await state.db.db.commit()


async def test_audio_block_429_when_budget_exhausted(client):
    await _set_code_budget(used=300, limit=300)
    files, data = _audio_form()
    # Transcription must NOT be called when the budget is exhausted.
    with patch("backend.routers.audio.get_transcription_service") as mock_get:
        res = await client.post("/api/audio-block", files=files, data=data)
        assert res.status_code == 429
        mock_get.assert_not_called()


async def test_audio_block_413_when_block_too_large(client):
    await _set_code_budget(used=0, limit=300)
    big = {"audio": ("block.webm", b"y" * 50, "audio/webm")}
    with patch("backend.routers.audio.MAX_AUDIO_BLOCK_BYTES", 10), \
         patch("backend.routers.audio.get_transcription_service") as mock_get:
        res = await client.post("/api/audio-block", files=big, data={"session_id": "s-ep"})
        assert res.status_code == 413
        mock_get.assert_not_called()


async def test_audio_block_passes_and_reports_remaining(client):
    await _set_code_budget(used=60, limit=300)
    files, data = _audio_form()

    mock_tx = MagicMock()
    mock_tx.transcribe = MagicMock(return_value=("Sprecher A: hi", 30.0))
    mock_ex = MagicMock()
    mock_ex.resolve_labels_async = AsyncMock(return_value="Anna: hi")
    mock_ex.extract_claims_async = AsyncMock(return_value=[])

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_tx), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_ex):
        res = await client.post("/api/audio-block", files=files, data=data)

    assert res.status_code == 202
    # remaining reflects the pre-increment budget at request time: 300 - 60 = 240
    assert res.json()["remaining_seconds"] == 240
    # background task ran and metered the 30s of audio: 60 -> 90
    assert (await state.db.get_code(TEST_ACCESS_CODE))["audio_seconds_used"] == 90


async def test_audio_block_unlimited_code_bypasses_budget(client):
    await _set_code_budget(used=99999, limit=None)
    files, data = _audio_form()
    mock_tx = MagicMock()
    mock_tx.transcribe = MagicMock(return_value=("Sprecher A: hi", 10.0))
    mock_ex = MagicMock()
    mock_ex.resolve_labels_async = AsyncMock(return_value="Anna: hi")
    mock_ex.extract_claims_async = AsyncMock(return_value=[])
    with patch("backend.routers.audio.get_transcription_service", return_value=mock_tx), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_ex):
        res = await client.post("/api/audio-block", files=files, data=data)
    assert res.status_code == 202
    assert res.json()["remaining_seconds"] is None


async def test_audio_block_overshoot_then_blocks(client):
    # used just below limit: first block passes (and overshoots), next is 429.
    await _set_code_budget(used=295, limit=300)
    files, data = _audio_form()
    mock_tx = MagicMock()
    mock_tx.transcribe = MagicMock(return_value=("Sprecher A: hi", 30.0))
    mock_ex = MagicMock()
    mock_ex.resolve_labels_async = AsyncMock(return_value="Anna: hi")
    mock_ex.extract_claims_async = AsyncMock(return_value=[])
    with patch("backend.routers.audio.get_transcription_service", return_value=mock_tx), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_ex):
        first = await client.post("/api/audio-block", files=files, data=data)
        assert first.status_code == 202
    # 295 + 30 = 325 >= 300 -> next request blocked
    assert (await state.db.get_code(TEST_ACCESS_CODE))["audio_seconds_used"] == 325
    second = await client.post("/api/audio-block", files=_audio_form()[0], data={"session_id": "s-ep"})
    assert second.status_code == 429
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest backend/tests/test_live_audio_limits.py -v -k audio_block`
Expected: FAIL — no `MAX_AUDIO_BLOCK_BYTES`, no `remaining_seconds`, no 429/413 guards, background still calls `transcribe` with the old single-string mock signature.

- [ ] **Step 3: Add `remaining_seconds` to `ProcessingResponse`**

In `backend/models.py`, add one field to `ProcessingResponse`:

```python
class ProcessingResponse(BaseModel):
    """Response for endpoints that start background processing."""
    status: str
    message: Optional[str] = None
    session_id: Optional[str] = None
    claims_count: Optional[int] = None
    source_id: Optional[str] = None
    block_id: Optional[str] = None
    remaining_seconds: Optional[int] = None
```

- [ ] **Step 4: Add imports + the byte-cap constant in `audio.py`**

In `backend/routers/audio.py`, add `HTTPException` to the FastAPI import line:

```python
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form
```

And below `AUDIO_TMP_DIR = "/tmp/factcheck_blocks"`, add:

```python
# Upper bound on a single uploaded audio block, enforced before any paid
# transcription. Our recorder sends ~60-180s blocks (well under this); the cap
# bounds the "one giant block" abuse vector. Overridable via env.
MAX_AUDIO_BLOCK_BYTES = int(os.getenv("MAX_AUDIO_BLOCK_BYTES", str(25 * 1024 * 1024)))
```

- [ ] **Step 5: Add the guards + `remaining_seconds` + thread the code into the handler**

In `backend/routers/audio.py`, replace the body of `receive_audio_block` from `audio_data = await audio.read()` down through the `return ProcessingResponse(...)` with:

```python
    audio_data = await audio.read()
    ep_key = session_id

    # Pre-call guard A — budget. None limit means unlimited.
    limit = code.get("audio_seconds_limit")
    used = code.get("audio_seconds_used", 0)
    if limit is not None and used >= limit:
        raise HTTPException(status_code=429, detail="Audio-Kontingent aufgebraucht")

    # Pre-call guard B — block size, bounded before we pay for transcription.
    if len(audio_data) > MAX_AUDIO_BLOCK_BYTES:
        raise HTTPException(status_code=413, detail="Audio-Block zu groß")

    remaining_seconds = None if limit is None else max(limit - used, 0)

    # Generate block_id here so it can be tracked immediately
    now = datetime.now(timezone.utc)
    block_id = f"block_{int(now.timestamp() * 1000)}"

    logger.info(f"Received audio block {block_id}: {len(audio_data)} bytes, session: {ep_key}")

    # Save audio to temp file for transcription and potential retrigger (dir guaranteed by startup)
    audio_path = _audio_file_path(block_id)
    with open(audio_path, "wb") as f:
        f.write(audio_data)

    # Register pipeline event
    state.pipeline_events[block_id] = {
        "block_id": block_id,
        "status": "processing",
        "started_at": now.isoformat(),
        "session_id": ep_key,
        "audio_file": audio_path,
        "message": None,
    }

    # Start background processing (pass path, not bytes, to avoid holding memory in handler)
    background_tasks.add_task(process_audio_pipeline_async, block_id, audio_path, ep_key, code["code"])

    return ProcessingResponse(
        status="processing",
        message="Audio received, processing started",
        block_id=block_id,
        remaining_seconds=remaining_seconds,
    )
```

> The background-signature change (`code` param + increment) lands in Task 5. After this step the endpoint guard tests (429/413) pass; the passthrough/overshoot tests still fail until Task 5.

- [ ] **Step 6: Run the guard tests to verify 429/413 pass**

Run: `uv run pytest backend/tests/test_live_audio_limits.py -v -k "429 or 413"`
Expected: PASS (`test_audio_block_429_when_budget_exhausted`, `test_audio_block_413_when_block_too_large`).

- [ ] **Step 7: Commit**

```bash
git add backend/models.py backend/routers/audio.py backend/tests/test_live_audio_limits.py
git commit -m "feat(audio): pre-call budget/size guards + remaining_seconds"
```

---

## Task 5: Background pipeline increments the budget

**Files:**
- Modify: `backend/routers/audio.py` (`process_audio_pipeline_async` ~line 98-138)
- Test: `backend/tests/test_audio_pipeline.py` (update 4 mocks + add increment assertion); finishes the Task 4 passthrough/overshoot tests.

- [ ] **Step 1: Update the existing pipeline test mocks + add an increment test**

In `backend/tests/test_audio_pipeline.py`, every `mock_transcription.transcribe = MagicMock(return_value=...)` must return a `(text, duration)` tuple. Change the four occurrences:

```python
    mock_transcription.transcribe = MagicMock(return_value=(raw_transcript, 30.0))
```

and (for the two tests that use an inline string):

```python
    mock_transcription.transcribe = MagicMock(return_value=("Sprecher A: Test.", 30.0))
```

Each call to `process_audio_pipeline_async(...)` gains a 4th positional arg — the code. For the existing tests pass `None` (no metering under test):

```python
        await process_audio_pipeline_async("test-block", mock_audio_file, "test-session", None)
```

Then add a new test:

```python
async def test_pipeline_increments_audio_seconds_for_code(mock_audio_file):
    """The transcribed audio_duration is added to the code's lifetime budget."""
    mock_transcription = MagicMock()
    mock_transcription.transcribe = MagicMock(return_value=("Sprecher A: Test.", 47.0))

    mock_extractor = MagicMock()
    mock_extractor.resolve_labels_async = AsyncMock(return_value="Anna: Test.")
    mock_extractor.extract_claims_async = AsyncMock(return_value=[])

    state.last_transcript_tail = None
    state.pipeline_events["inc-block"] = {"status": "processing"}
    await state.get_db().add_code("inc-code", "ann")
    await state.get_db().add_session({"session_id": "inc-sess", "title": "t", "guests": [], "context": ""})

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_transcription), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_extractor):
        await process_audio_pipeline_async("inc-block", mock_audio_file, "inc-sess", "inc-code")

    assert (await state.get_db().get_code("inc-code"))["audio_seconds_used"] == 47
```

- [ ] **Step 2: Run the pipeline tests to verify they fail**

Run: `uv run pytest backend/tests/test_audio_pipeline.py -v`
Expected: FAIL — `process_audio_pipeline_async()` takes 3 positional args (no `code`); transcript is now a tuple so `len(transcript)` / downstream string ops break.

- [ ] **Step 3: Add the `code` param, unpack the tuple, and increment**

In `backend/routers/audio.py`, change the signature:

```python
async def process_audio_pipeline_async(block_id: str, audio_path: str, session_id: str, code: str | None = None):
```

Unpack the transcribe result — replace the `transcript = await asyncio.wait_for(...)` assignment so it captures both values:

```python
        try:
            transcript, audio_duration = await asyncio.wait_for(
                asyncio.to_thread(transcription_service.transcribe, audio_data, ep_keyterms),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            logger.error(f"[{block_id}] Transcription timed out after 60 seconds. AssemblyAI is likely stuck in 'processing' state.")
            slow_task.cancel()
            _set_event_status(block_id, "timeout", "Transkription nach 60s abgebrochen (AssemblyAI hängt)")
            return

        slow_task.cancel()
        logger.info(f"[{block_id}] Transcription complete: {len(transcript)} chars")

        # Meter the real audio length against the code's lifetime budget. Runs
        # right after a successful (paid) transcription, before extraction, so
        # even claim-free audio counts. check-before/increment-after: at most one
        # block overshoots the budget, then the code is closed.
        if code is not None and audio_duration > 0:
            await db.increment_audio_seconds(code, int(round(audio_duration)))
```

- [ ] **Step 4: Run the pipeline + endpoint tests to verify they pass**

Run: `uv run pytest backend/tests/test_audio_pipeline.py backend/tests/test_live_audio_limits.py -v`
Expected: PASS — including the Task-4 `passthrough`, `unlimited`, and `overshoot` endpoint tests that depend on this increment.

- [ ] **Step 5: Lint + run the full backend suite (unit only)**

Run: `uv run ruff check backend/ && uv run pytest backend/tests -m "not integration" -q`
Expected: ruff clean; all unit tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/audio.py backend/tests/test_audio_pipeline.py
git commit -m "feat(audio): meter transcribed seconds into per-code budget"
```

---

## Task 6: Frontend — `sendAudioBlock` flags 429 + returns remaining

**Files:**
- Modify: `frontend/src/services/api.js` (`sendAudioBlock` ~line 129-148)
- Test: `frontend/src/services/api.test.js`

- [ ] **Step 1: Write the failing api test**

In `frontend/src/services/api.test.js`, add (match the file's existing fetch-mock style — `global.fetch = vi.fn(...)`):

```js
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { sendAudioBlock } from './api'

describe('sendAudioBlock quota handling', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('throws a quota-flagged error on 429', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false, status: 429,
      json: async () => ({ detail: 'Audio-Kontingent aufgebraucht' }),
    })
    await expect(sendAudioBlock('s1', new Blob(['x'])))
      .rejects.toMatchObject({ isQuota: true })
  })

  it('returns remaining_seconds on success', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, status: 202,
      json: async () => ({ status: 'processing', block_id: 'b1', remaining_seconds: 180 }),
    })
    const data = await sendAudioBlock('s1', new Blob(['x']))
    expect(data.remaining_seconds).toBe(180)
  })
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && bun run test -- api.test.js`
Expected: FAIL — the rejected error has no `isQuota` property.

- [ ] **Step 3: Flag the 429 in `sendAudioBlock`**

In `frontend/src/services/api.js`, replace the error branch of `sendAudioBlock`:

```js
  const data = await safeJsonParse(res, 'sendAudioBlock')
  if (!res.ok) {
    const err = new Error(data?.detail || `sendAudioBlock failed (${res.status})`)
    if (res.status === 429) err.isQuota = true   // budget exhausted -> caller stops recording
    throw err
  }
  return data  // { status, message, block_id, remaining_seconds }
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && bun run test -- api.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/api.js frontend/src/services/api.test.js
git commit -m "feat(api): flag 429 audio-quota errors, expose remaining_seconds"
```

---

## Task 7: Frontend — recorder stops on quota + tracks remaining

**Files:**
- Modify: `frontend/src/hooks/useAudioRecorder.js` (MSG ~line 7-12; state ~line 14-19; `flush` ~line 54-74; return ~line 123-127)
- Test: `frontend/src/hooks/useAudioRecorder.test.js`

- [ ] **Step 1: Write the failing hook test**

In `frontend/src/hooks/useAudioRecorder.test.js`, add a test that drives `flush` into a quota rejection. Match the file's existing `renderHook` + `MediaRecorder` mock setup; the essential assertions:

```js
it('stops recording and reports quota error when a block is rejected with 429', async () => {
  const quotaErr = new Error('Audio-Kontingent aufgebraucht')
  quotaErr.isQuota = true
  sendAudioBlock.mockRejectedValueOnce(quotaErr)   // sendAudioBlock is vi.mock'd at top of file

  const { result } = renderHook(() => useAudioRecorder('s1'))
  await act(async () => { await result.current.start() })
  await act(async () => { await result.current.sendNow() })  // triggers flush -> rejected

  expect(result.current.status).toBe('idle')                 // recorder stopped
  expect(result.current.error).toMatch(/Kontingent/)
})

it('exposes remaining seconds from a successful block', async () => {
  sendAudioBlock.mockResolvedValueOnce({ status: 'processing', remaining_seconds: 90 })
  const { result } = renderHook(() => useAudioRecorder('s1'))
  await act(async () => { await result.current.start() })
  await act(async () => { await result.current.sendNow() })
  expect(result.current.remainingSeconds).toBe(90)
})
```

> If `sendAudioBlock` is not yet mocked in this file, add `vi.mock('../services/api', () => ({ sendAudioBlock: vi.fn() }))` at the top and `import { sendAudioBlock } from '../services/api'`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && bun run test -- useAudioRecorder.test.js`
Expected: FAIL — `remainingSeconds` is undefined; on quota error the hook stays `recording`.

- [ ] **Step 3: Add a quota message + remaining state**

In `frontend/src/hooks/useAudioRecorder.js`, add to `MSG`:

```js
  quota: 'Audio-Kontingent für diesen Code aufgebraucht',
```

Add state next to the others:

```js
  const [remainingSeconds, setRemainingSeconds] = useState(null)
```

- [ ] **Step 4: Handle quota + remaining in `flush`**

Replace the `try { await sendAudioBlock(...) } catch { ... }` block in `flush`:

```js
    try {
      const data = await sendAudioBlock(sessionId, blob)
      setBlocksSent((n) => n + 1)
      setError(null)   // a recovered send clears a prior send-failure indicator
      if (data && data.remaining_seconds !== undefined) {
        setRemainingSeconds(data.remaining_seconds)
      }
    } catch (e) {
      if (e && e.isQuota) {
        // Budget exhausted: stop the session and surface a clear message.
        setError(MSG.quota)
        setRemainingSeconds(0)
        stoppingRef.current = true
        clearTimers()
        if (streamRef.current) {
          streamRef.current.getTracks().forEach((t) => t.stop())
          streamRef.current = null
        }
        recorderRef.current = null
        setElapsed(0)
        setStatus('idle')
        return
      }
      // One bad block must not kill the session: surface, keep recording.
      setError(MSG.sendFailed)
    }
```

> `flush` already restarted a fresh recorder before the `try` (line ~63). On quota we tear that recorder down again here, so the session ends cleanly. Add `clearTimers` to `flush`'s dependency array (`[sessionId, startRecorder, clearTimers]`).

- [ ] **Step 5: Expose `remainingSeconds`**

In the hook's return object, add `remainingSeconds`:

```js
  return {
    status, elapsed, blocksSent, error,
    blockSeconds, setBlockSeconds,
    remainingSeconds,
    start, sendNow, stop,
  }
```

- [ ] **Step 6: Run to verify it passes**

Run: `cd frontend && bun run test -- useAudioRecorder.test.js`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/hooks/useAudioRecorder.js frontend/src/hooks/useAudioRecorder.test.js
git commit -m "feat(recorder): stop on audio-quota 429, track remaining seconds"
```

---

## Task 8: Frontend — show "noch M:SS übrig" in the recording bar

**Files:**
- Modify: `frontend/src/components/RecordingBar.jsx` (destructure ~line 12-15; recording branch ~line 22-36)

- [ ] **Step 1: Surface `remainingSeconds` while recording**

In `frontend/src/components/RecordingBar.jsx`, pull `remainingSeconds` from the recorder:

```jsx
  const {
    status, elapsed, blocksSent, error,
    blockSeconds, setBlockSeconds, start, sendNow, stop,
    remainingSeconds,
  } = recorder
```

In the `isRecording` branch, after the "Blöcke gesendet" span, add a remaining indicator (only when the code is limited, i.e. not `null`/`undefined`):

```jsx
          {remainingSeconds != null && (
            <span className="recording-bar-remaining">
              noch {formatElapsed(Math.max(remainingSeconds, 0))} übrig
            </span>
          )}
```

> `formatElapsed` already renders `M:SS` and is defined at the top of this file — reuse it.

- [ ] **Step 2: Build the frontend to verify it compiles**

Run: `cd frontend && bun run build`
Expected: build succeeds with no errors.

- [ ] **Step 3: Run the full frontend test suite**

Run: `cd frontend && bun run test`
Expected: PASS (api, recorder, and any RecordingBar tests).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/RecordingBar.jsx
git commit -m "feat(ui): show remaining audio time in recording bar"
```

---

## Task 9: Deployment docs

**Files:**
- Modify: `docs/deployment.md` (env section + a runbook note next to the existing Quick-Check unlimited-owner note)

- [ ] **Step 1: Document the env var + the unlimited-owner migration wrinkle**

In `docs/deployment.md`, add `LIVE_AUDIO_LIMIT_MINUTES` to the env list (default `5`, sets the per-code lifetime audio cap), and add a runbook note mirroring the Quick-Check one:

```markdown
### Live-Audio-Limit (Phase 3b)

- `LIVE_AUDIO_LIMIT_MINUTES` (default `5`) sets the lifetime audio cap per code,
  applied at seeding as `audio_seconds_limit = minutes * 60`.
- The DB migration backfills **existing** codes to 300s (5 min) — fail-closed, not
  unlimited. After deploy, every old code is capped at 5 minutes of live audio.
- Unlimited-owner wrinkle: a code already seeded as `unlimited` is **not** updated
  to NULL by `INSERT OR IGNORE` and will sit at the 300s backfill. To make it
  truly unlimited again:
  `sqlite3 /opt/fact_check/backend/data/factcheck.db "UPDATE codes SET audio_seconds_limit=NULL WHERE code='<code>'"`
- Per-code overrides are DB edits (no 4th `ACCESS_CODES` field):
  `... "UPDATE codes SET audio_seconds_limit=<seconds> WHERE code='<code>'"`
- `MAX_AUDIO_BLOCK_BYTES` (default ~25 MB) bounds a single uploaded block; raise
  only if legitimate blocks ever exceed it.
```

> Adapt the DB path to whatever `docs/deployment.md` already uses for the Quick-Check sqlite example.

- [ ] **Step 2: Commit**

```bash
git add docs/deployment.md
git commit -m "docs: document LIVE_AUDIO_LIMIT_MINUTES + audio-quota runbook"
```

---

## Final Verification

- [ ] **Backend, unit only:** `uv run pytest backend/tests -m "not integration" -q` → all pass
- [ ] **Lint:** `uv run ruff check backend/` → clean
- [ ] **Frontend tests:** `cd frontend && bun run test` → all pass
- [ ] **Frontend build:** `cd frontend && bun run build` → succeeds

---

## Spec Coverage Check

- Metric = real audio seconds → Task 3 (`audio_duration`) + Task 5 (increment). ✅
- Cumulative per code (lifetime) → Task 1 columns + `increment_audio_seconds`. ✅
- Default 5 min, env-configurable → Task 2 (`LIVE_AUDIO_LIMIT_MINUTES`). ✅
- Unlimited codes bypass audio limit → Task 2 seeding heuristic + Task 4 `limit is None` guard + `test_audio_block_unlimited_code_bypasses_budget`. ✅
- New columns + idempotent migration, fail-closed `DEFAULT 300` backfill → Task 1. ✅
- `ACCESS_CODES` syntax unchanged → `parse_access_codes` untouched (Task 2 note). ✅
- Pre-call guard A (429, no paid call) → Task 4 + `test_audio_block_429...` asserts `transcribe` not called. ✅
- Pre-call guard B (413, `MAX_AUDIO_BLOCK_BYTES`) → Task 4 + `test_audio_block_413...`. ✅
- `transcribe()` → `(str, float)`, callers updated → Task 3 + Task 5. ✅
- Increment after call; one block overshoots then blocks → Task 5 + `test_audio_block_overshoot_then_blocks`. ✅
- Response `remaining_seconds` (None when unlimited) → Task 4 model + handler. ✅
- Frontend: catch 429 → stop + message → Task 6 + Task 7. ✅
- Frontend: "noch X:XX übrig" header → Task 8. ✅
- Deployment notes (env, fail-closed backfill, owner wrinkle) → Task 9. ✅
- Out of scope (text path, Quick-Check, reset/admin, per-session cap) → untouched. ✅
```
