"""Tests for Quick Check (Phase Q): codes quota columns, env parsing/seeding,
and the POST /api/quick-check endpoint."""

import pytest

from backend.database import Database


@pytest.fixture
async def fresh_db():
    db = Database(":memory:")
    await db.connect()
    yield db
    await db.close()


# ---------------------------------------------------------------------------
# DB layer: quota columns on `codes`
# ---------------------------------------------------------------------------

async def test_add_code_defaults_limit_to_3_and_used_to_0(fresh_db):
    await fresh_db.add_code("c1", "ulf")
    row = await fresh_db.get_code("c1")
    assert row["quick_checks_used"] == 0
    assert row["quick_check_limit"] == 3


async def test_add_code_accepts_unlimited_via_none(fresh_db):
    await fresh_db.add_code("owner", "ulf", quick_check_limit=None)
    row = await fresh_db.get_code("owner")
    assert row["quick_check_limit"] is None


async def test_add_code_accepts_custom_limit(fresh_db):
    await fresh_db.add_code("c5", "ann", quick_check_limit=5)
    assert (await fresh_db.get_code("c5"))["quick_check_limit"] == 5


async def test_increment_quick_checks(fresh_db):
    await fresh_db.add_code("c1", "ulf")
    await fresh_db.increment_quick_checks("c1")
    await fresh_db.increment_quick_checks("c1")
    assert (await fresh_db.get_code("c1"))["quick_checks_used"] == 2
