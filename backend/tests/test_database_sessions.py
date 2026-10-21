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


async def test_delete_session_deletes_its_transcript(db):
    await db.add_session({"session_id": "tr1", "title": "T"})
    await db.upsert_transcript_turns([
        {"session_id": "tr1", "turn_order": 0, "speaker_label": "A", "text": "Satz eins."},
        {"session_id": "tr2", "turn_order": 0, "speaker_label": "A", "text": "Andere Sitzung."},
    ])
    assert await db.delete_session("tr1")
    assert await db.get_transcript("tr1") == []
    assert len(await db.get_transcript("tr2")) == 1


async def test_purge_transcripts_removes_old_turns_only(db):
    from datetime import datetime, timedelta
    await db.upsert_transcript_turns([
        {"session_id": "p1", "turn_order": 0, "text": "Alt."},
        {"session_id": "p1", "turn_order": 1, "text": "Neu."},
    ])
    old = (datetime.now() - timedelta(days=31)).isoformat()
    await db.db.execute("UPDATE transcript_turns SET created_at = ? WHERE turn_order = 0", (old,))
    await db.db.commit()

    assert await db.purge_transcripts(30) == 1
    assert [t["text"] for t in await db.get_transcript("p1")] == ["Neu."]


async def test_transcript_update_keeps_created_at(db):
    await db.upsert_transcript_turns([{"session_id": "u1", "turn_order": 0, "text": "Erst."}])
    first = (await db.get_transcript("u1"))[0]
    await db.upsert_transcript_turns([{"session_id": "u1", "turn_order": 0, "speaker_name": "Dröge",
                                       "text": "Erst korrigiert."}])
    [turn] = await db.get_transcript("u1")
    assert turn["text"] == "Erst korrigiert." and turn["speaker_name"] == "Dröge"
    assert turn["created_at"] == first["created_at"]
