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
        "type": "show",
    })
    assert sid == "abc123"
    s = await db.get_session("abc123")
    assert s["title"] == "Maischberger"
    assert s["guests"] == ["Sandra Maischberger (Moderatorin)", "Gast (CDU)"]
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


async def test_add_session_persists_conversation_type():
    from backend.database import Database
    db = Database(":memory:")
    await db.connect()
    await db.add_session({"session_id": "ct1", "title": "T", "conversation_type": "interview",
                          "created_at": "2026-06-11"})
    s = await db.get_session("ct1")
    assert s["conversation_type"] == "interview"
    await db.close()


async def test_add_session_defaults_conversation_type_to_debate():
    from backend.database import Database
    db = Database(":memory:")
    await db.connect()
    await db.add_session({"session_id": "ct2", "title": "T", "created_at": "2026-06-11"})
    s = await db.get_session("ct2")
    assert s["conversation_type"] == "debate"
    await db.close()


async def test_session_round_trips_excluded_speakers(db):
    await db.add_session({
        "session_id": "exc1",
        "title": "T",
        "guests": ["Caren Miosga (Moderatorin)"],
        "excluded_speakers": ["Caren Miosga"],
    })
    s = await db.get_session("exc1")
    assert s["excluded_speakers"] == ["Caren Miosga"]


async def test_session_defaults_excluded_speakers_empty(db):
    await db.add_session({"session_id": "exc2", "title": "T"})
    s = await db.get_session("exc2")
    assert s["excluded_speakers"] == []


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
