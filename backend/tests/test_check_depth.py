"""
Tests for the check_depth column (SG-5): two-tier fast/deep fact-checks.
"""

import pytest
from datetime import datetime

from backend.database import Database


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


def _row(check_depth=None):
    d = {
        "sprecher": "X",
        "behauptung": "Y",
        "consistency": "hoch",
        "begruendung": "kurz",
        "quellen": [],
        "timestamp": datetime.now().isoformat(),
        "session_id": "s1",
        "status": "",
    }
    if check_depth is not None:
        d["check_depth"] = check_depth
    return d


async def test_default_check_depth_is_deep(db):
    """Rows written without an explicit depth read back as 'deep'."""
    fid = await db.add_fact_check(_row())
    row = await db.get_fact_check_by_id(fid)
    assert row["check_depth"] == "deep"


async def test_fast_row_roundtrips(db):
    fid = await db.add_fact_check(_row(check_depth="fast"))
    row = await db.get_fact_check_by_id(fid)
    assert row["check_depth"] == "fast"


async def test_upgrade_fast_to_deep(db):
    """A fast row updated by the deep path (no check_depth in dict) flips to 'deep'."""
    fid = await db.add_fact_check(_row(check_depth="fast"))
    assert (await db.get_fact_check_by_id(fid))["check_depth"] == "fast"
    await db.update_fact_check(fid, _row())  # deep result dict, no check_depth
    assert (await db.get_fact_check_by_id(fid))["check_depth"] == "deep"


async def test_migration_on_legacy_table(db):
    """A pre-existing fact_checks table without check_depth is migrated in place."""
    # Drop and recreate the legacy schema (no check_depth), then re-run migrations.
    await db.db.execute("DROP TABLE fact_checks")
    await db.db.execute(
        """CREATE TABLE fact_checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sprecher TEXT NOT NULL DEFAULT '', behauptung TEXT NOT NULL DEFAULT '',
            consistency TEXT NOT NULL DEFAULT '', begruendung TEXT NOT NULL DEFAULT '',
            quellen TEXT NOT NULL DEFAULT '[]', timestamp TEXT NOT NULL,
            session_id TEXT, status TEXT NOT NULL DEFAULT '',
            double_check INTEGER NOT NULL DEFAULT 0, critique_note TEXT NOT NULL DEFAULT ''
        )"""
    )
    await db.db.execute(
        "INSERT INTO fact_checks (behauptung, timestamp) VALUES ('legacy', ?)",
        (datetime.now().isoformat(),),
    )
    await db.db.commit()

    await db.init_schema()  # idempotent; applies the check_depth migration

    cursor = await db.db.execute("SELECT check_depth FROM fact_checks WHERE behauptung='legacy'")
    row = await cursor.fetchone()
    assert row[0] == "deep"
