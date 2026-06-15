# Session Multi-Tenancy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single global `current_episode_key` with runtime-created, DB-backed sessions so many fact-check shows can run in parallel, fully isolated by `session_id`.

**Architecture:** Generalize the hardcoded `Episode`/`EPISODES` concept into a `sessions` table. The DB column `episode_key` is renamed to `session_id` in both tables; legacy episodes are seeded into `sessions` with their old key as `session_id`, so existing fact-checks map 1:1 without data migration. The existing semaphore-based queue worker is reused; queue items carry `session_id`. No WebSockets, no homepage redesign, no access-code gating (those are later phases).

**Tech Stack:** Python 3.12, FastAPI, aiosqlite (SQLite + WAL), pytest (async), React + Vite (frontend), uv (Python), bun (frontend).

**Spec:** `docs/superpowers/specs/2026-06-09-session-multitenancy-design.md`

**Conventions:**
- Run unit tests with: `uv run pytest backend/tests -m "not integration"`
- Lint with: `uv run ruff check --fix backend/`
- Commit messages: short, one line, no co-author (per CLAUDE.md).
- Each task ends green: the full unit suite passes.

---

## File Structure

**Backend — modified:**
- `backend/database.py` — add `sessions` table + session CRUD; rename `episode_key`→`session_id` column and internals.
- `config.py` — add `Episode.from_session_row()` factory + `episode_to_session_dict()` helper.
- `backend/state.py` — remove `current_episode_key`.
- `backend/models.py` — add session request/response models; rename `episode_key`→`session_id` fields.
- `backend/utils.py` — `build_fact_check_dict` param/key rename.
- `backend/routers/audio.py`, `claims.py`, `fact_checks.py`, `config.py` — `session_id` scoping, session-table lookups.
- `backend/app.py` — seed legacy episodes into `sessions` on startup; include sessions router.
- `backend/tests/conftest.py` — drop `current_episode_key` reset.
- `listener.py` — send `session_id`.

**Backend — created:**
- `backend/routers/sessions.py` — session CRUD endpoints.
- `backend/tests/test_database_sessions.py` — session CRUD + isolation tests.
- `backend/tests/test_api_sessions.py` — session endpoint tests.

**Frontend — modified:**
- `frontend/src/services/api.js` — session API helpers.
- `frontend/src/App.jsx` — add `/new` route.
- `frontend/src/pages/` + `components/AdminView.jsx` — scope by `session_id`, create-session form.

---

## Task 1: `sessions` table schema + Database CRUD

**Files:**
- Modify: `backend/database.py` (`init_schema`, add session methods)
- Test: `backend/tests/test_database_sessions.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_database_sessions.py`:

```python
"""Tests for sessions table CRUD."""
import pytest
from backend.database import Database


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


async def test_sessions_table_exists(db):
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'"
    )
    assert await cursor.fetchone() is not None


async def test_add_and_get_session(db):
    sid = await db.add_session({
        "session_id": "abc123",
        "title": "Maischberger",
        "date": "9. Juni 2026",
        "guests": ["Sandra Maischberger (Moderatorin)", "Gast (CDU)"],
        "context": "Testkontext",
        "reference_links": ["https://example.com"],
        "type": "show",
    })
    assert sid == "abc123"
    s = await db.get_session("abc123")
    assert s["title"] == "Maischberger"
    assert s["guests"] == ["Sandra Maischberger (Moderatorin)", "Gast (CDU)"]
    assert s["reference_links"] == ["https://example.com"]
    assert s["status"] == "active"
    assert s["visibility"] == "private"


async def test_get_missing_session_returns_none(db):
    assert await db.get_session("nope") is None


async def test_list_sessions(db):
    await db.add_session({"session_id": "a", "title": "A"})
    await db.add_session({"session_id": "b", "title": "B"})
    sessions = await db.list_sessions()
    assert {s["session_id"] for s in sessions} == {"a", "b"}


async def test_end_session(db):
    await db.add_session({"session_id": "a", "title": "A"})
    ok = await db.end_session("a")
    assert ok is True
    s = await db.get_session("a")
    assert s["status"] == "ended"
    assert s["ended_at"] is not None


async def test_seed_session_if_absent_is_idempotent(db):
    row = {"session_id": "leg", "title": "Legacy", "visibility": "public", "status": "ended"}
    await db.seed_session_if_absent(row)
    await db.seed_session_if_absent({**row, "title": "CHANGED"})
    s = await db.get_session("leg")
    assert s["title"] == "Legacy"  # not overwritten
    assert s["visibility"] == "public"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_database_sessions.py -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'add_session'` (and missing table).

- [ ] **Step 3: Add the `sessions` table to `init_schema`**

In `backend/database.py`, inside `init_schema`'s `executescript(...)`, after the `pending_claims_blocks` table, add:

```sql
            CREATE TABLE IF NOT EXISTS sessions (
                session_id       TEXT PRIMARY KEY,
                title            TEXT NOT NULL DEFAULT '',
                date             TEXT NOT NULL DEFAULT '',
                guests           TEXT NOT NULL DEFAULT '[]',
                context          TEXT NOT NULL DEFAULT '',
                reference_links  TEXT NOT NULL DEFAULT '[]',
                type             TEXT NOT NULL DEFAULT 'show',
                status           TEXT NOT NULL DEFAULT 'active',
                visibility       TEXT NOT NULL DEFAULT 'private',
                owner_code       TEXT,
                created_at       TEXT NOT NULL,
                ended_at         TEXT
            );
```

- [ ] **Step 4: Add session CRUD methods**

In `backend/database.py`, add a new section before `# Pending Claims Blocks CRUD`:

```python
    # =========================================================================
    # Sessions CRUD
    # =========================================================================

    def _row_to_session(self, row) -> dict:
        return {
            "session_id": row["session_id"],
            "title": row["title"],
            "date": row["date"],
            "guests": json.loads(row["guests"]),
            "context": row["context"],
            "reference_links": json.loads(row["reference_links"]),
            "type": row["type"],
            "status": row["status"],
            "visibility": row["visibility"],
            "owner_code": row["owner_code"],
            "created_at": row["created_at"],
            "ended_at": row["ended_at"],
        }

    async def add_session(self, session: dict) -> str:
        """Insert a session. Returns its session_id."""
        from datetime import datetime
        await self.db.execute(
            """INSERT INTO sessions
               (session_id, title, date, guests, context, reference_links,
                type, status, visibility, owner_code, created_at, ended_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session["session_id"],
                session.get("title", ""),
                session.get("date", ""),
                json.dumps(session.get("guests", []), ensure_ascii=False),
                session.get("context", ""),
                json.dumps(session.get("reference_links", []), ensure_ascii=False),
                session.get("type", "show"),
                session.get("status", "active"),
                session.get("visibility", "private"),
                session.get("owner_code"),
                session.get("created_at", datetime.now().isoformat()),
                session.get("ended_at"),
            ),
        )
        await self.db.commit()
        return session["session_id"]

    async def get_session(self, session_id: str) -> dict | None:
        cursor = await self.db.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        )
        row = await cursor.fetchone()
        return self._row_to_session(row) if row else None

    async def list_sessions(self) -> list[dict]:
        cursor = await self.db.execute("SELECT * FROM sessions ORDER BY created_at DESC")
        return [self._row_to_session(r) for r in await cursor.fetchall()]

    async def end_session(self, session_id: str) -> bool:
        from datetime import datetime
        cursor = await self.db.execute(
            "UPDATE sessions SET status = 'ended', ended_at = ? WHERE session_id = ?",
            (datetime.now().isoformat(), session_id),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def seed_session_if_absent(self, session: dict) -> None:
        """Insert a session only if its session_id does not already exist."""
        existing = await self.get_session(session["session_id"])
        if existing is None:
            await self.add_session(session)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_database_sessions.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix backend/database.py
git add backend/database.py backend/tests/test_database_sessions.py
git commit -m "Add sessions table and CRUD to database"
```

---

## Task 2: Rename DB column `episode_key` → `session_id`

This renames the physical column **and** the Python interface (method params + dict keys) in `backend/database.py`, plus the migration. Callers are fixed in later tasks; to keep this task green we update the existing DB tests here too.

**Files:**
- Modify: `backend/database.py`
- Modify: `backend/tests/test_database.py`

- [ ] **Step 1: Update existing DB tests to the new name**

In `backend/tests/test_database.py`, replace every `"episode_key"` dict key and every `episode_key=` kwarg with `"session_id"` / `session_id=`. (Search the file: `grep -n episode_key backend/tests/test_database.py` and update each hit.) Example:

```python
        "session_id": "test-episode",
```
```python
    rows = await db.get_fact_checks(session_id="test-episode")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest backend/tests/test_database.py -v`
Expected: FAIL — the DB layer still uses `episode_key` (KeyError / unexpected kwarg).

- [ ] **Step 3: Add the column-rename migration**

In `backend/database.py` `init_schema`, after the existing `for migration in [...]` block, add an idempotent rename:

```python
        # Migration: rename episode_key -> session_id (SQLite >= 3.25)
        for table in ("fact_checks", "pending_claims_blocks"):
            cursor = await self.db.execute(f"PRAGMA table_info({table})")
            cols = [r[1] for r in await cursor.fetchall()]
            if "episode_key" in cols and "session_id" not in cols:
                await self.db.execute(
                    f"ALTER TABLE {table} RENAME COLUMN episode_key TO session_id"
                )
                await self.db.commit()
```

Also update the two `CREATE TABLE` statements in the `executescript`: change `episode_key TEXT,` / `episode_key TEXT` to `session_id TEXT,` / `session_id TEXT` in both `fact_checks` and `pending_claims_blocks`.

- [ ] **Step 4: Rename in DB methods**

In `backend/database.py`, apply these exact renames (column name in SQL, dict keys, kwargs):
- `_fact_check_params`: `data.get("episode_key")` → `data.get("session_id")`.
- `add_fact_check`: column list `episode_key` → `session_id`.
- `get_fact_checks(self, episode_key=..., ...)`: param → `session_id`; the `if episode_key:` block uses `"session_id = ?"` and `params.append(session_id)`.
- `update_fact_check`: SQL `episode_key = ?` → `session_id = ?`.
- `_row_to_fact_check`: `"episode_key": row["episode_key"]` → `"session_id": row["session_id"]`.
- `add_pending_block`: column `episode_key` → `session_id`; value `block.get("episode_key")` → `block.get("session_id")`.
- `get_pending_blocks(self, episode_key=...)`: param → `session_id`; SQL `WHERE episode_key = ?` → `WHERE session_id = ?`.
- `clear_pending_blocks(self, episode_key=...)`: param → `session_id`; SQL `WHERE episode_key = ?` → `WHERE session_id = ?`.
- `_row_to_pending_block`: `"episode_key": row["episode_key"]` → `"session_id": row["session_id"]`.

Verify none remain: `grep -n episode_key backend/database.py` must return nothing.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_database.py backend/tests/test_database_sessions.py -v`
Expected: PASS. (Other suites are still red until later tasks — that's expected; do NOT run the full suite at this step.)

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix backend/database.py
git add backend/database.py backend/tests/test_database.py
git commit -m "Rename episode_key column to session_id in DB layer"
```

---

## Task 3: `Episode.from_session_row` factory + `episode_to_session_dict`

**Files:**
- Modify: `config.py`
- Test: `backend/tests/test_config_sessions.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_config_sessions.py`:

```python
"""Tests for Episode <-> session-row mapping."""
from config import Episode, EPISODES, episode_to_session_dict


def test_from_session_row_builds_episode():
    row = {
        "session_id": "abc",
        "title": "maischberger",
        "date": "9. Juni 2026",
        "guests": ["Sandra Maischberger (Moderatorin)", "Gast (CDU)"],
        "context": "Kontext",
        "reference_links": [],
        "type": "show",
    }
    ep = Episode.from_session_row(row)
    assert ep.key == "abc"
    assert ep.show == "maischberger"
    assert ep.date == "9. Juni 2026"
    assert ep.speakers == ["Sandra Maischberger", "Gast"]
    assert ep.context == "Kontext"


def test_episode_to_session_dict_roundtrip():
    ep = EPISODES["maischberger-2025-09-19"]
    d = episode_to_session_dict(ep)
    assert d["session_id"] == "maischberger-2025-09-19"
    assert d["title"] == "maischberger"
    assert d["guests"] == ep.guests
    assert d["visibility"] == "public"
    assert d["status"] == "ended"
    ep2 = Episode.from_session_row(d)
    assert ep2.speakers == ep.speakers
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest backend/tests/test_config_sessions.py -v`
Expected: FAIL — `ImportError: cannot import name 'episode_to_session_dict'`.

- [ ] **Step 3: Implement factory + helper**

In `config.py`, add a classmethod to the `Episode` dataclass (after the `episode_name` property):

```python
    @classmethod
    def from_session_row(cls, row: dict) -> "Episode":
        """Build an Episode view-model from a sessions-table row dict."""
        return cls(
            key=row["session_id"],
            show=row.get("title", ""),
            date=row.get("date", ""),
            guests=row.get("guests", []),
            context=row.get("context", ""),
            reference_links=row.get("reference_links", []),
            type=row.get("type", "show"),
            publish=row.get("visibility") == "public",
        )
```

At module level (after the helper functions at the bottom), add:

```python
from datetime import datetime as _datetime

def episode_to_session_dict(ep: Episode) -> dict:
    """Convert a hardcoded Episode into a sessions-table row dict (for seeding)."""
    return {
        "session_id": ep.key,
        "title": ep.show,
        "date": ep.date,
        "guests": ep.guests,
        "context": ep.context,
        "reference_links": ep.reference_links,
        "type": ep.type,
        "status": "ended",
        "visibility": "public" if ep.publish else "private",
        "created_at": _datetime.now().isoformat(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_config_sessions.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix config.py
git add config.py backend/tests/test_config_sessions.py
git commit -m "Add Episode<->session-row mapping helpers"
```

---

## Task 4: Seed legacy episodes into `sessions` on startup

**Files:**
- Modify: `backend/app.py` (lifespan)
- Test: `backend/tests/test_seed_sessions.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_seed_sessions.py`:

```python
"""Seeding legacy EPISODES into the sessions table."""
import pytest
from backend.database import Database
from backend.app import seed_legacy_episodes
from config import EPISODES


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


async def test_seed_inserts_all_episodes(db):
    await seed_legacy_episodes(db)
    sessions = await db.list_sessions()
    assert len(sessions) == len(EPISODES)
    one = await db.get_session("maischberger-2025-09-19")
    assert one is not None
    assert one["visibility"] == "public"


async def test_seed_is_idempotent(db):
    await seed_legacy_episodes(db)
    await seed_legacy_episodes(db)
    sessions = await db.list_sessions()
    assert len(sessions) == len(EPISODES)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest backend/tests/test_seed_sessions.py -v`
Expected: FAIL — `ImportError: cannot import name 'seed_legacy_episodes'`.

- [ ] **Step 3: Implement seeding**

In `backend/app.py`, add an import and a function (top-level, after imports):

```python
from config import EPISODES, episode_to_session_dict


async def seed_legacy_episodes(db) -> None:
    """Seed hardcoded EPISODES into the sessions table (idempotent)."""
    for ep in EPISODES.values():
        await db.seed_session_if_absent(episode_to_session_dict(ep))
```

In the `lifespan` function, right after `state.db = db` and before starting the queue worker, add:

```python
    await seed_legacy_episodes(db)
    logger.info("Legacy episodes seeded into sessions table")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_seed_sessions.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix backend/app.py
git add backend/app.py backend/tests/test_seed_sessions.py
git commit -m "Seed legacy episodes into sessions table on startup"
```

---

## Task 5: Session request/response models

**Files:**
- Modify: `backend/models.py`

- [ ] **Step 1: Add models (no separate test — exercised in Task 6)**

In `backend/models.py`, add under the Request Models section:

```python
class CreateSessionRequest(BaseModel):
    """Request body for POST /api/sessions."""
    title: str
    date: str = ""
    guests: List[str] = []
    context: str = ""
    reference_links: List[str] = []
    type: str = "show"
```

And under Response Models:

```python
class SessionResponse(BaseModel):
    """A session as returned by the API."""
    session_id: str
    title: str
    date: str = ""
    guests: List[str] = []
    context: str = ""
    reference_links: List[Any] = []
    type: str = "show"
    status: str = "active"
    visibility: str = "private"
    created_at: Optional[str] = None
    ended_at: Optional[str] = None
```

- [ ] **Step 2: Verify import works**

Run: `uv run python -c "from backend.models import CreateSessionRequest, SessionResponse; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add backend/models.py
git commit -m "Add session request/response models"
```

---

## Task 6: Sessions router (create / get / end)

**Files:**
- Create: `backend/routers/sessions.py`
- Modify: `backend/app.py` (include router)
- Test: `backend/tests/test_api_sessions.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_api_sessions.py`:

```python
"""Tests for the sessions API."""
import pytest


async def test_create_session_returns_id(client):
    resp = await client.post("/api/sessions", json={
        "title": "Mein Interview",
        "guests": ["Moderator (Host)", "Gast (Experte)"],
        "context": "Thema X",
    })
    assert resp.status_code == 201
    body = resp.json()
    assert body["session_id"]
    assert body["status"] == "active"
    assert body["visibility"] == "private"


async def test_get_session(client):
    sid = (await client.post("/api/sessions", json={"title": "T"})).json()["session_id"]
    resp = await client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "T"


async def test_get_missing_session_404(client):
    resp = await client.get("/api/sessions/does-not-exist")
    assert resp.status_code == 404


async def test_end_session(client):
    sid = (await client.post("/api/sessions", json={"title": "T"})).json()["session_id"]
    resp = await client.post(f"/api/sessions/{sid}/end")
    assert resp.status_code == 200
    assert (await client.get(f"/api/sessions/{sid}")).json()["status"] == "ended"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest backend/tests/test_api_sessions.py -v`
Expected: FAIL — 404 for `/api/sessions` (router not registered).

- [ ] **Step 3: Implement the router**

Create `backend/routers/sessions.py`:

```python
"""Session management endpoints."""
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException

from backend.models import CreateSessionRequest, SessionResponse
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/sessions", status_code=201, response_model=SessionResponse)
async def create_session(request: CreateSessionRequest):
    db = state.get_db()
    session_id = uuid.uuid4().hex[:12]
    row = {
        "session_id": session_id,
        "title": request.title,
        "date": request.date,
        "guests": request.guests,
        "context": request.context,
        "reference_links": request.reference_links,
        "type": request.type,
        "status": "active",
        "visibility": "private",
        "created_at": datetime.now().isoformat(),
    }
    await db.add_session(row)
    logger.info(f"Session created: {session_id} ({request.title})")
    return SessionResponse(**await db.get_session(session_id))


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    db = state.get_db()
    s = await db.get_session(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    return SessionResponse(**s)


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: str):
    db = state.get_db()
    if not await db.end_session(session_id):
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    return {"status": "ended", "session_id": session_id}
```

In `backend/app.py`, add `sessions` to the routers import and registration:

```python
from backend.routers import audio, claims, fact_checks, config, pipeline, sessions
```
```python
app.include_router(sessions.router)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_api_sessions.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix backend/routers/sessions.py backend/app.py
git add backend/routers/sessions.py backend/app.py backend/tests/test_api_sessions.py
git commit -m "Add sessions router (create/get/end)"
```

---

## Task 7: `build_fact_check_dict` rename

**Files:**
- Modify: `backend/utils.py`
- Modify: `backend/tests/test_utils.py`

- [ ] **Step 1: Update the test**

In `backend/tests/test_utils.py`, find tests calling `build_fact_check_dict` and asserting the `"episode_key"` key; change the positional call's expectation to assert `result["session_id"]`. (Run `grep -n "episode_key\|build_fact_check_dict" backend/tests/test_utils.py` and update each.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest backend/tests/test_utils.py -v`
Expected: FAIL — result dict still has key `episode_key`.

- [ ] **Step 3: Rename in `build_fact_check_dict`**

In `backend/utils.py`, change the signature param `episode_key: str` → `session_id: str` and the returned dict key `"episode_key": episode_key` → `"session_id": session_id`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest backend/tests/test_utils.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix backend/utils.py
git add backend/utils.py backend/tests/test_utils.py
git commit -m "Rename build_fact_check_dict episode_key param to session_id"
```

---

## Task 8: Scope audio router by `session_id`

**Files:**
- Modify: `backend/routers/audio.py`
- Modify: `backend/tests/test_audio_pipeline.py`

- [ ] **Step 1: Update tests**

In `backend/tests/test_audio_pipeline.py`, replace `episode_key` form fields / assertions with `session_id`, and where a test relied on `EPISODES`-based context, insert a session first via `state.get_db().add_session({...})`. (Run `grep -n episode backend/tests/test_audio_pipeline.py` and update each call site to pass `session_id` and seed a session row.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest backend/tests/test_audio_pipeline.py -v`
Expected: FAIL — endpoint still expects `episode_key` / reads `EPISODES`.

- [ ] **Step 3: Rewrite the endpoint + pipeline**

In `backend/routers/audio.py`:

- Change `receive_audio_block` signature: `episode_key: Optional[str] = Form(default=None)` → `session_id: str = Form(...)` (required).
- Remove `ep_key = episode_key or state.current_episode_key or ''`; use `ep_key = session_id`.
- In `state.pipeline_events[block_id]`, rename the `"episode_key": ep_key` field to `"session_id": ep_key`.
- `ProcessingResponse(... episode_key=ep_key ...)` → keep `ProcessingResponse` but set `session_id` (see Task 11 model note) — for now pass `block_id` only and drop `episode_key=`.
- In `process_audio_pipeline_async(block_id, audio_path, session_id)`: replace the `EPISODES.get(episode_key)` lookup with a session lookup:

```python
    db = state.get_db()
    session = await db.get_session(session_id)
    from config import Episode
    ep = Episode.from_session_row(session) if session else None
    ep_guests = ep.guests if ep else []
    ep_date = ep.date if ep else ""
    ep_context = ep.context if ep else ""
```

- In the `pending_block` dict and the AUTO_APPROVE placeholder dicts, rename key `"episode_key": episode_key` → `"session_id": session_id`.
- In the AUTO_APPROVE call, `process_fact_checks_async(selected, episode_key, ...)` → `process_fact_checks_async(selected, session_id, ...)`.
- Remove the now-unused `from config import EPISODES` import if no longer referenced.

Verify: `grep -n episode_key backend/routers/audio.py` returns nothing.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest backend/tests/test_audio_pipeline.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check --fix backend/routers/audio.py
git add backend/routers/audio.py backend/tests/test_audio_pipeline.py
git commit -m "Scope audio pipeline by session_id"
```

---

## Task 9: Scope claims router by `session_id`

**Files:**
- Modify: `backend/routers/claims.py`
- Modify: `backend/models.py` (rename `episode_key` fields)
- Modify: `backend/tests/test_api_claims.py`

- [ ] **Step 1: Update models**

In `backend/models.py`, rename `episode_key: Optional[str]` → `session_id: Optional[str]` in `ClaimApprovalRequest` and `PendingClaimsRequest`. (Leave `FactCheckRequest`/`ClaimUpdateRequest` for Task 10.)

- [ ] **Step 2: Update tests**

In `backend/tests/test_api_claims.py`, update request bodies/asserts: `episode_key` → `session_id`; the `episode=` query param on `GET /pending-claims` becomes `session_id=` (see endpoint change below). Seed a session where a test needs context from config. (Run `grep -n "episode" backend/tests/test_api_claims.py`.)

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest backend/tests/test_api_claims.py -v`
Expected: FAIL.

- [ ] **Step 4: Rewrite the router**

In `backend/routers/claims.py`:

- `process_text_pipeline_async`: the `pending_block` dict — replace `"episode_key": state.current_episode_key or "test"` with a required `session_id` parameter. Change the signature to `process_text_pipeline_async(text, headline, source_id, session_id, publication_date=None)` and `"session_id": session_id`. Update the AUTO_APPROVE placeholder dict key and `process_fact_checks_async(selected, session_id, ...)`.
- `receive_text_block`: add `session_id` to `TextBlockRequest` (in `backend/models.py` add `session_id: str` to `TextBlockRequest`) and pass `request.session_id` into the background task.
- `get_pending_claims(episode=None)` → `get_pending_claims(session_id: str | None = None)`; call `db.get_pending_blocks(session_id=session_id)`.
- `receive_pending_claims`: `episode_key = request.session_id` (remove `or state.current_episode_key`); `pending_block["session_id"] = episode_key` (rename key).
- `discard_claims`: `session_id = request.session_id`; placeholder dict key `"session_id"`.
- `approve_claims`: `session_id = request.session_id`. Replace context lookup:

```python
    db = state.get_db()
    context = None
    session = await db.get_session(session_id) if session_id else None
    if session:
        context = session["context"]
    elif request.block_id:
        block = await db.get_pending_block_by_id(request.block_id)
        if block:
            context = block.get("headline", "")
            if not session_id:
                session_id = block.get("session_id")
```

  Placeholder dicts use `"session_id": session_id`. Enqueue tuple becomes `(request.claims, session_id, context, placeholder_ids)`.
- `process_fact_checks_async(claims, episode_key, ...)` → rename param to `session_id`; replace `EPISODES[episode_key].date if episode_key in EPISODES` with:

```python
    session = await state.get_db().get_session(session_id) if session_id else None
    episode_date = session["date"] if session else None
```

  and `build_fact_check_dict(to_dict(result), session_id)`.
- `claim_queue_worker`: rename the unpacked tuple var `episode_key` → `session_id` in both `run_batch` and the `while` loop (and the inner `_batch_and_done`). Pass `session_id` through. The semaphore logic is unchanged.
- Remove `from config import EPISODES` if now unused.

Verify: `grep -n "episode_key\|current_episode_key\|EPISODES" backend/routers/claims.py` returns nothing.

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest backend/tests/test_api_claims.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix backend/routers/claims.py backend/models.py
git add backend/routers/claims.py backend/models.py backend/tests/test_api_claims.py
git commit -m "Scope claims pipeline by session_id"
```

---

## Task 10: Scope fact_checks router by `session_id`

**Files:**
- Modify: `backend/routers/fact_checks.py`
- Modify: `backend/models.py` (`FactCheckRequest`, `ClaimUpdateRequest`)
- Modify: `backend/tests/test_api_fact_checks.py`

- [ ] **Step 1: Update models**

In `backend/models.py`: in `FactCheckRequest` rename `episode_key`→`session_id` (keep `episode` removed); in `ClaimUpdateRequest` rename `episode_key`→`session_id`.

- [ ] **Step 2: Update tests**

In `backend/tests/test_api_fact_checks.py`, update bodies/queries: `episode_key`→`session_id`; `GET /fact-checks?episode=` → `?session_id=`. (Run `grep -n episode backend/tests/test_api_fact_checks.py`.)

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest backend/tests/test_api_fact_checks.py -v`
Expected: FAIL.

- [ ] **Step 4: Rewrite the router**

In `backend/routers/fact_checks.py`:

- `get_fact_checks(episode=...)` → `get_fact_checks(session_id: Optional[str] = Query(default=None), ...)`; call `db.get_fact_checks(session_id=session_id, status=status)`.
- `receive_fact_check`: `episode_key = request.session_id` (drop `or state.current_episode_key`); fact_check dict key `"session_id": episode_key` → use var `session_id`.
- `update_fact_check` + `resend_fact_check`: `session_id = request.session_id or existing.get("session_id")` (drop `current_episode_key`); pass `session_id` to the background tasks.
- `process_new_fact_check_async` + `process_fact_check_update_async`: rename param `episode_key`→`session_id`; replace `EPISODES[episode_key].date if episode_key in EPISODES` with a session lookup:

```python
    session = await state.get_db().get_session(session_id) if session_id else None
    episode_date = session["date"] if session else None
```

  and `build_fact_check_dict(..., session_id, ...)`.
- Remove `from config import EPISODES` if now unused.

Verify: `grep -n "episode_key\|current_episode_key\|EPISODES" backend/routers/fact_checks.py` returns nothing.

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest backend/tests/test_api_fact_checks.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
uv run ruff check --fix backend/routers/fact_checks.py backend/models.py
git add backend/routers/fact_checks.py backend/models.py backend/tests/test_api_fact_checks.py
git commit -m "Scope fact_checks pipeline by session_id"
```

---

## Task 11: Config router + ProcessingResponse + remove `current_episode_key`

**Files:**
- Modify: `backend/routers/config.py`
- Modify: `backend/models.py` (`ProcessingResponse`, `HealthResponse`, remove `SetEpisodeRequest`)
- Modify: `backend/state.py`
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Write the failing config test**

Create `backend/tests/test_api_config.py`:

```python
import backend.state as state


async def test_shows_lists_seeded_session(client):
    db = state.get_db()
    await db.add_session({"session_id": "x1", "title": "maischberger", "visibility": "public"})
    resp = await client.get("/api/config/shows")
    assert resp.status_code == 200
    keys = [s["key"] for s in resp.json()["shows"]]
    assert "x1" in keys


async def test_session_config_404(client):
    resp = await client.get("/api/config/nope")
    assert resp.status_code == 404


async def test_health_reports_active_sessions(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert "active_sessions" in resp.json()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest backend/tests/test_api_config.py -v`
Expected: FAIL — `/api/config/shows` still reads `EPISODES`; `/api/health` still returns `current_episode`.

- [ ] **Step 3: Remove the global + ProcessingResponse field**

In `backend/state.py`, delete the line `current_episode_key: str | None = None`.

In `backend/models.py`:
- `ProcessingResponse`: rename `episode_key: Optional[str]` → `session_id: Optional[str]`.
- `HealthResponse`: rename `current_episode: Optional[str]` → `active_sessions: int`.
- Delete the `SetEpisodeRequest` class.

- [ ] **Step 4: Rewrite config router**

In `backend/routers/config.py`:
- Remove the `SetEpisodeRequest` import and the entire `set_current_episode` / `POST /set-episode` endpoint.
- `get_all_shows_endpoint`: read from the DB instead of `EPISODES`:

```python
@router.get('/config/shows', response_model=ShowsDetailedResponse)
async def get_all_shows_endpoint():
    db = state.get_db()
    sessions = await db.list_sessions()
    from config import Episode, get_show_name
    detailed = sorted(
        [
            {
                "key": s["session_id"],
                "name": get_show_name(s["title"]),
                "date": s["date"],
                "episode_name": Episode.from_session_row(s).episode_name,
                "type": s["type"],
                "publish": s["visibility"] == "public",
            }
            for s in sessions
        ],
        key=lambda x: x["key"], reverse=True,
    )
    return ShowsDetailedResponse(shows=detailed)
```

- `get_episode_config_endpoint(episode_key)`: rename path param to `session_id`, read from DB:

```python
@router.get('/config/{session_id}')
async def get_session_config_endpoint(session_id: str):
    db = state.get_db()
    s = await db.get_session(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    from config import Episode, get_show_name
    ep = Episode.from_session_row(s)
    return {**s, "speakers": ep.speakers, "show_name": get_show_name(s["title"])}
```

- `health`: replace `current_episode=state.current_episode_key` with `active_sessions=len([s for s in await db.list_sessions() if s["status"] == "active"])`.
- Leave `get_episodes_for_show_endpoint` as-is for now (legacy `get_episodes_for_show` reads `EPISODES`; still valid for seeded legacy shows). It can later read the DB (followup).

- [ ] **Step 5: Run to verify the config test passes**

Run: `uv run pytest backend/tests/test_api_config.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the FULL unit suite**

Run: `uv run pytest backend/tests -m "not integration" -v`
Expected: ALL PASS. Fix any remaining `current_episode_key`/`episode_key` references surfaced here:
`grep -rn "current_episode_key\|episode_key" backend/` must return nothing (outside comments).

- [ ] **Step 7: Commit**

```bash
uv run ruff check --fix backend/
git add backend/routers/config.py backend/models.py backend/state.py backend/tests/
git commit -m "Replace global current_episode_key with session-based config"
```

---

## Task 12: Isolation regression test (two parallel sessions)

**Files:**
- Test: `backend/tests/test_session_isolation.py` (create)

- [ ] **Step 1: Write the test**

Create `backend/tests/test_session_isolation.py`:

```python
"""Two sessions must not see each other's data."""


async def test_fact_checks_isolated_by_session(client):
    a = (await client.post("/api/sessions", json={"title": "A"})).json()["session_id"]
    b = (await client.post("/api/sessions", json={"title": "B"})).json()["session_id"]

    await client.post("/api/fact-checks", json={
        "sprecher": "X", "behauptung": "claim-A", "session_id": a,
    })
    await client.post("/api/fact-checks", json={
        "sprecher": "Y", "behauptung": "claim-B", "session_id": b,
    })

    fa = (await client.get(f"/api/fact-checks?session_id={a}")).json()
    fb = (await client.get(f"/api/fact-checks?session_id={b}")).json()
    assert [f["behauptung"] for f in fa] == ["claim-A"]
    assert [f["behauptung"] for f in fb] == ["claim-B"]


async def test_pending_claims_isolated_by_session(client):
    a = (await client.post("/api/sessions", json={"title": "A"})).json()["session_id"]
    b = (await client.post("/api/sessions", json={"title": "B"})).json()["session_id"]
    await client.post("/api/pending-claims", json={
        "claims": [{"name": "X", "claim": "c"}], "session_id": a,
    })
    pa = (await client.get(f"/api/pending-claims?session_id={a}")).json()
    pb = (await client.get(f"/api/pending-claims?session_id={b}")).json()
    assert len(pa) == 1 and len(pb) == 0
```

- [ ] **Step 2: Run to verify it passes**

Run: `uv run pytest backend/tests/test_session_isolation.py -v`
Expected: PASS (2 tests). If red, the scoping in Tasks 9–10 has a leak — fix there.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_session_isolation.py
git commit -m "Add session isolation regression tests"
```

---

## Task 13: Frontend — create-session form + session-scoped views

**Files:**
- Modify: `frontend/src/services/api.js`
- Modify: `frontend/src/App.jsx`
- Create: `frontend/src/pages/NewSessionPage.jsx`
- Modify: `frontend/src/components/AdminView.jsx` and the page that reads the route param

> The implementing agent MUST first read `frontend/src/App.jsx`, `frontend/src/pages/FactCheckPage.jsx`, and `frontend/src/components/AdminView.jsx` to match existing patterns (state, fetch helpers, styling). The route param `:episodeKey` already maps to a session id (legacy ids are unchanged), so the **view** path needs no change — only creation + admin actions must send `session_id`.

- [ ] **Step 1: Add API helpers**

In `frontend/src/services/api.js`, add:

```javascript
export async function createSession(payload) {
  const res = await fetch(`${BACKEND_URL}/api/sessions`, {
    method: 'POST', headers: FETCH_HEADERS, body: JSON.stringify(payload),
  })
  return safeJsonParse(res, 'createSession')
}

export async function endSession(sessionId) {
  const res = await fetch(`${BACKEND_URL}/api/sessions/${sessionId}/end`, {
    method: 'POST', headers: FETCH_HEADERS,
  })
  return safeJsonParse(res, 'endSession')
}
```

- [ ] **Step 2: Add the create-session page**

Create `frontend/src/pages/NewSessionPage.jsx` — a form (title, date, guests as one-per-line textarea, context textarea, reference links textarea) that on submit calls `createSession({ title, date, guests, context, reference_links })`, then `navigate('/' + result.session_id)`. Use `useNavigate` from `react-router-dom`. Parse `guests`/`reference_links` textareas by splitting on newlines and trimming empties.

- [ ] **Step 3: Register the route**

In `frontend/src/App.jsx`, import `NewSessionPage` and add **before** the `/:episodeKey` wildcard route:

```jsx
          <Route path="/new" element={<NewSessionPage />} />
```

- [ ] **Step 4: Send `session_id` from admin actions**

In `frontend/src/components/AdminView.jsx` (and any caller), every request body that currently sends `episode_key` / query `episode=` must send `session_id` / `session_id=` using the current route's session id. Grep the frontend: `grep -rn "episode_key\|episode=" frontend/src` and update each to `session_id`.

- [ ] **Step 5: Build to verify**

Run: `cd frontend && bun run build`
Expected: build succeeds with no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "Frontend: create-session form and session_id scoping"
```

---

## Task 14: Update `listener.py` to send `session_id`

**Files:**
- Modify: `listener.py`

- [ ] **Step 1: Replace set-episode with session usage**

In `listener.py`:
- Remove `set_backend_episode` (the `POST /api/set-episode` call no longer exists) and its call at line ~375.
- The CLI arg previously named "episode key" / `SHOW` is now a **session id**. Rename the variable to `session_id` for clarity.
- In the audio-block POST (line ~156), change the form field `'episode_key': self.show` → `'session_id': self.session_id`.

- [ ] **Step 2: Smoke-check the script imports**

Run: `uv run python -c "import ast; ast.parse(open('listener.py').read()); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add listener.py
git commit -m "listener: send session_id instead of episode_key"
```

---

## Final Verification

- [ ] **Full unit suite green**

Run: `uv run pytest backend/tests -m "not integration"`
Expected: ALL PASS.

- [ ] **No stale references**

Run: `grep -rn "current_episode_key\|episode_key" backend/ listener.py frontend/src`
Expected: no matches (comments/docstrings may be updated separately).

- [ ] **Lint clean**

Run: `uv run ruff check backend/`
Expected: no errors.

- [ ] **Frontend builds**

Run: `cd frontend && bun run build`
Expected: success.

---

## Spec Coverage Notes

- §3 Datenmodell → Tasks 1, 2, 3.
- §2a DB-Rolle (sessions persist) → Tasks 1, 4.
- §4 Runtime/Nebenläufigkeit (reuse semaphore, items carry session_id, remove `current_episode_key`) → Tasks 9, 11.
- §5 API changes (session CRUD, session_id everywhere, config from DB) → Tasks 6, 8–11.
- §6 Frontend minimal (create form, scope views, shareable `/{session_id}`) → Task 13.
- §7 Migration + tests (rename, seed legacy, isolation) → Tasks 2, 4, 12.

## Out of scope (later phases, per spec §8)

Browser audio capture (Phase 2), access codes + `owner_code` (Phase 3), VPS deployment + JSON-export removal (Phase 4), homepage/IA redesign (Phase 1b), auto-expiry of stale `active` sessions.
