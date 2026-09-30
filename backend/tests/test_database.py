"""
Tests for the SQLite database module.

All tests use in-memory SQLite (:memory:) for isolation and speed.
"""

import pytest
from datetime import datetime

from backend.database import Database


@pytest.fixture
async def db():
    """Create an in-memory database for each test."""
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


# =============================================================================
# Schema & Connection
# =============================================================================


async def test_connect_and_schema(db):
    """Tables should exist after connect."""
    cursor = await db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in await cursor.fetchall()]
    assert "fact_checks" in tables
    assert "pending_claims_blocks" in tables


async def test_schema_idempotent(db):
    """Calling init_schema twice should not error."""
    await db.init_schema()
    count = await db.count_fact_checks()
    assert count == 0


# =============================================================================
# Fact-Checks CRUD
# =============================================================================


async def test_add_and_get_fact_check(db):
    """Add a fact-check and retrieve it."""
    fc = {
        "sprecher": "Max Mustermann",
        "behauptung": "Die Erde ist flach",
        "consistency": "falsch",
        "begruendung": "Wissenschaftliche Evidenz zeigt das Gegenteil",
        "quellen": [{"url": "https://example.com", "title": "Quelle"}],
        "timestamp": datetime.now().isoformat(),
        "session_id": "test-episode",
    }
    new_id = await db.add_fact_check(fc)
    assert new_id >= 1

    result = await db.get_fact_check_by_id(new_id)
    assert result is not None
    assert result["id"] == new_id
    assert result["sprecher"] == "Max Mustermann"
    assert result["behauptung"] == "Die Erde ist flach"
    assert result["consistency"] == "falsch"
    assert result["quellen"] == [{"url": "https://example.com", "title": "Quelle"}]
    assert result["session_id"] == "test-episode"
    assert result["double_check"] is False
    assert result["critique_note"] == ""


async def test_add_fact_check_with_double_check(db):
    """double_check and critique_note are stored and retrieved correctly."""
    fc = {
        "sprecher": "Speaker",
        "behauptung": "Eine wortlautabhängige Behauptung",
        "consistency": "unklar",
        "begruendung": "Begründung",
        "quellen": [],
        "timestamp": datetime.now().isoformat(),
        "double_check": True,
        "critique_note": "Urteil hängt stark von der Formulierung ab.",
    }
    new_id = await db.add_fact_check(fc)
    result = await db.get_fact_check_by_id(new_id)

    assert result["double_check"] is True
    assert result["critique_note"] == "Urteil hängt stark von der Formulierung ab."


async def test_update_fact_check_double_check(db):
    """Updating a fact-check persists changes to double_check and critique_note."""
    fc = {
        "sprecher": "Speaker",
        "behauptung": "Behauptung",
        "consistency": "hoch",
        "begruendung": "",
        "quellen": [],
        "timestamp": datetime.now().isoformat(),
        "double_check": False,
        "critique_note": "",
    }
    new_id = await db.add_fact_check(fc)

    fc["double_check"] = True
    fc["critique_note"] = "Neuer Vorbehalt"
    await db.update_fact_check(new_id, fc)

    result = await db.get_fact_check_by_id(new_id)
    assert result["double_check"] is True
    assert result["critique_note"] == "Neuer Vorbehalt"


async def test_get_fact_check_not_found(db):
    """Getting a non-existent ID returns None."""
    result = await db.get_fact_check_by_id(999)
    assert result is None


async def test_get_fact_checks_all(db):
    """Get all fact-checks."""
    for i in range(3):
        await db.add_fact_check({
            "sprecher": f"Speaker {i}",
            "behauptung": f"Claim {i}",
            "consistency": "richtig",
            "begruendung": "",
            "quellen": [],
            "timestamp": datetime.now().isoformat(),
            "session_id": "ep1" if i < 2 else "ep2",
        })

    all_fcs = await db.get_fact_checks()
    assert len(all_fcs) == 3


async def test_get_fact_checks_filtered(db):
    """Filter fact-checks by session_id."""
    for i in range(3):
        await db.add_fact_check({
            "sprecher": f"Speaker {i}",
            "behauptung": f"Claim {i}",
            "consistency": "richtig",
            "begruendung": "",
            "quellen": [],
            "timestamp": datetime.now().isoformat(),
            "session_id": "ep1" if i < 2 else "ep2",
        })

    ep1 = await db.get_fact_checks(session_id="ep1")
    assert len(ep1) == 2

    ep2 = await db.get_fact_checks(session_id="ep2")
    assert len(ep2) == 1


async def test_update_fact_check(db):
    """Update an existing fact-check."""
    fc_id = await db.add_fact_check({
        "sprecher": "Old Speaker",
        "behauptung": "Old Claim",
        "consistency": "unklar",
        "begruendung": "",
        "quellen": [],
        "timestamp": datetime.now().isoformat(),
        "session_id": "ep1",
    })

    updated = await db.update_fact_check(fc_id, {
        "sprecher": "New Speaker",
        "behauptung": "New Claim",
        "consistency": "richtig",
        "begruendung": "Updated evidence",
        "quellen": [{"url": "https://new.com", "title": "New"}],
        "timestamp": datetime.now().isoformat(),
        "session_id": "ep1",
    })
    assert updated is True

    result = await db.get_fact_check_by_id(fc_id)
    assert result["sprecher"] == "New Speaker"
    assert result["consistency"] == "richtig"
    assert result["quellen"] == [{"url": "https://new.com", "title": "New"}]


async def test_update_nonexistent_fact_check(db):
    """Updating a non-existent ID returns False."""
    result = await db.update_fact_check(999, {
        "sprecher": "",
        "behauptung": "",
        "consistency": "",
        "begruendung": "",
        "quellen": [],
        "timestamp": datetime.now().isoformat(),
    })
    assert result is False


async def test_count_fact_checks(db):
    """Count returns correct number."""
    assert await db.count_fact_checks() == 0

    await db.add_fact_check({
        "sprecher": "A",
        "behauptung": "B",
        "consistency": "richtig",
        "begruendung": "",
        "quellen": [],
        "timestamp": datetime.now().isoformat(),
    })
    assert await db.count_fact_checks() == 1


async def test_autoincrement_ids(db):
    """IDs should auto-increment."""
    id1 = await db.add_fact_check({
        "sprecher": "A",
        "behauptung": "B",
        "consistency": "",
        "begruendung": "",
        "quellen": [],
        "timestamp": datetime.now().isoformat(),
    })
    id2 = await db.add_fact_check({
        "sprecher": "C",
        "behauptung": "D",
        "consistency": "",
        "begruendung": "",
        "quellen": [],
        "timestamp": datetime.now().isoformat(),
    })
    assert id2 > id1


# =============================================================================
# JSON Serialization
# =============================================================================


async def test_json_quellen_roundtrip(db):
    """Complex quellen (sources) survive JSON serialization."""
    sources = [
        {"url": "https://example.com/1", "title": "Quelle 1", "snippet": "Text..."},
        {"url": "https://example.com/2", "title": "Quelle mit Ümlauten"},
    ]
    fc_id = await db.add_fact_check({
        "sprecher": "Test",
        "behauptung": "Test",
        "consistency": "richtig",
        "begruendung": "",
        "quellen": sources,
        "timestamp": datetime.now().isoformat(),
    })

    result = await db.get_fact_check_by_id(fc_id)
    assert result["quellen"] == sources


# =============================================================================
# Delete Fact-Check
# =============================================================================


class TestDeleteFactCheck:
    """Tests for Database.delete_fact_check()."""

    async def test_delete_existing_fact_check(self, db):
        """delete_fact_check returns True and removes the row."""
        fact_check_id = await db.add_fact_check({
            "sprecher": "Speaker A",
            "behauptung": "Some claim",
            "timestamp": "2024-01-01T10:00:00",
        })

        result = await db.delete_fact_check(fact_check_id)

        assert result is True
        assert await db.get_fact_check_by_id(fact_check_id) is None

    async def test_delete_nonexistent_fact_check(self, db):
        """delete_fact_check returns False for unknown ID."""
        result = await db.delete_fact_check(9999)

        assert result is False

    async def test_delete_does_not_affect_other_rows(self, db):
        """delete_fact_check only removes the targeted row."""
        id1 = await db.add_fact_check({"sprecher": "A", "behauptung": "C1", "timestamp": "2024-01-01T10:00:00"})
        id2 = await db.add_fact_check({"sprecher": "B", "behauptung": "C2", "timestamp": "2024-01-01T11:00:00"})

        await db.delete_fact_check(id1)

        remaining = await db.get_fact_checks()
        assert len(remaining) == 1
        assert remaining[0]["id"] == id2
