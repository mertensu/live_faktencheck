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
        "episode_key": "test-episode",
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
    assert result["episode_key"] == "test-episode"


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
            "episode_key": "ep1" if i < 2 else "ep2",
        })

    all_fcs = await db.get_fact_checks()
    assert len(all_fcs) == 3


async def test_get_fact_checks_filtered(db):
    """Filter fact-checks by episode_key."""
    for i in range(3):
        await db.add_fact_check({
            "sprecher": f"Speaker {i}",
            "behauptung": f"Claim {i}",
            "consistency": "richtig",
            "begruendung": "",
            "quellen": [],
            "timestamp": datetime.now().isoformat(),
            "episode_key": "ep1" if i < 2 else "ep2",
        })

    ep1 = await db.get_fact_checks(episode_key="ep1")
    assert len(ep1) == 2

    ep2 = await db.get_fact_checks(episode_key="ep2")
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
        "episode_key": "ep1",
    })

    updated = await db.update_fact_check(fc_id, {
        "sprecher": "New Speaker",
        "behauptung": "New Claim",
        "consistency": "richtig",
        "begruendung": "Updated evidence",
        "quellen": [{"url": "https://new.com", "title": "New"}],
        "timestamp": datetime.now().isoformat(),
        "episode_key": "ep1",
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


async def test_find_fact_check(db):
    """Find fact-check by speaker + claim."""
    await db.add_fact_check({
        "sprecher": "Alice",
        "behauptung": "Claim A",
        "consistency": "richtig",
        "begruendung": "",
        "quellen": [],
        "timestamp": "2024-01-01T00:00:00",
        "episode_key": "ep1",
    })
    await db.add_fact_check({
        "sprecher": "Alice",
        "behauptung": "Claim A",
        "consistency": "falsch",
        "begruendung": "Updated",
        "quellen": [],
        "timestamp": "2024-01-02T00:00:00",
        "episode_key": "ep1",
    })

    result = await db.find_fact_check("Alice", "Claim A")
    assert result is not None
    # Should return newest (highest ID)
    assert result["consistency"] == "falsch"


async def test_find_fact_check_not_found(db):
    """Finding a non-existent speaker+claim returns None."""
    result = await db.find_fact_check("Nobody", "Nothing")
    assert result is None


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


async def test_json_claims_roundtrip(db):
    """Complex claims survive JSON serialization in pending blocks."""
    claims = [
        {"name": "Alice", "claim": "Behauptung mit Ümlauten", "context": "Kontext"},
        {"name": "Bob", "claim": "Another claim"},
    ]
    await db.add_pending_block({
        "block_id": "test-json",
        "timestamp": datetime.now().isoformat(),
        "claims_count": len(claims),
        "claims": claims,
        "status": "pending",
    })

    result = await db.get_pending_block_by_id("test-json")
    assert result["claims"] == claims


# =============================================================================
# Pending Claims Blocks CRUD
# =============================================================================


async def test_add_and_get_pending_block(db):
    """Add a pending block and retrieve it."""
    block = {
        "block_id": "block_123",
        "timestamp": datetime.now().isoformat(),
        "claims_count": 2,
        "claims": [{"name": "A", "claim": "X"}, {"name": "B", "claim": "Y"}],
        "status": "pending",
        "episode_key": "ep1",
        "source_id": "article-001",
        "headline": "Test Headline",
        "text_preview": "Preview text...",
        "info": "Extra info",
    }
    row_id = await db.add_pending_block(block)
    assert row_id >= 1

    result = await db.get_pending_block_by_id("block_123")
    assert result is not None
    assert result["block_id"] == "block_123"
    assert result["claims_count"] == 2
    assert len(result["claims"]) == 2
    assert result["headline"] == "Test Headline"
    assert result["info"] == "Extra info"


async def test_get_pending_blocks_sorted(db):
    """Pending blocks are returned newest first."""
    await db.add_pending_block({
        "block_id": "old",
        "timestamp": "2024-01-01T00:00:00",
        "claims": [],
        "status": "pending",
    })
    await db.add_pending_block({
        "block_id": "new",
        "timestamp": "2024-06-01T00:00:00",
        "claims": [],
        "status": "pending",
    })

    blocks = await db.get_pending_blocks()
    assert len(blocks) == 2
    assert blocks[0]["block_id"] == "new"
    assert blocks[1]["block_id"] == "old"


async def test_block_id_exists(db):
    """Check if a block_id exists."""
    assert await db.block_id_exists("nope") is False

    await db.add_pending_block({
        "block_id": "exists",
        "timestamp": datetime.now().isoformat(),
        "claims": [],
        "status": "pending",
    })
    assert await db.block_id_exists("exists") is True


async def test_block_id_unique_constraint(db):
    """Duplicate block_id should raise an error."""
    block = {
        "block_id": "dup",
        "timestamp": datetime.now().isoformat(),
        "claims": [],
        "status": "pending",
    }
    await db.add_pending_block(block)

    with pytest.raises(Exception):
        await db.add_pending_block(block)


async def test_delete_pending_block(db):
    """Delete a pending block."""
    await db.add_pending_block({
        "block_id": "to-delete",
        "timestamp": datetime.now().isoformat(),
        "claims": [],
        "status": "pending",
    })
    assert await db.count_pending_blocks() == 1

    deleted = await db.delete_pending_block("to-delete")
    assert deleted is True
    assert await db.count_pending_blocks() == 0


async def test_delete_nonexistent_block(db):
    """Deleting a non-existent block returns False."""
    result = await db.delete_pending_block("nope")
    assert result is False


async def test_count_pending_blocks(db):
    """Count returns correct number."""
    assert await db.count_pending_blocks() == 0

    await db.add_pending_block({
        "block_id": "b1",
        "timestamp": datetime.now().isoformat(),
        "claims": [],
        "status": "pending",
    })
    await db.add_pending_block({
        "block_id": "b2",
        "timestamp": datetime.now().isoformat(),
        "claims": [],
        "status": "pending",
    })
    assert await db.count_pending_blocks() == 2


async def test_pending_block_not_found(db):
    """Getting a non-existent block_id returns None."""
    result = await db.get_pending_block_by_id("nope")
    assert result is None


async def test_pending_block_optional_fields(db):
    """Optional fields default to None."""
    await db.add_pending_block({
        "block_id": "minimal",
        "timestamp": datetime.now().isoformat(),
        "claims": [],
        "status": "pending",
    })

    result = await db.get_pending_block_by_id("minimal")
    assert result["episode_key"] is None
    assert result["source_id"] is None
    assert result["headline"] is None
    assert result["text_preview"] is None
    assert result["info"] is None
