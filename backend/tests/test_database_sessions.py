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
