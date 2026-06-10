"""Tests for Quick Check (Phase Q): codes quota columns, env parsing/seeding,
and the POST /api/quick-check endpoint."""

import pytest

from backend.database import Database
from backend.auth import parse_access_codes, seed_codes_from_env


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


# ---------------------------------------------------------------------------
# Env parsing: optional third "limit" field
# ---------------------------------------------------------------------------

def test_parse_access_codes_default_limit_is_3():
    assert parse_access_codes("ulf:s1") == [("ulf", "s1", 3)]


def test_parse_access_codes_unlimited():
    assert parse_access_codes("ulf:s1:unlimited") == [("ulf", "s1", None)]


def test_parse_access_codes_numeric_limit():
    assert parse_access_codes("ulf:s1:5") == [("ulf", "s1", 5)]


def test_parse_access_codes_bad_limit_falls_back_to_default():
    # A non-numeric, non-"unlimited" third field is treated as the default cap.
    assert parse_access_codes("ulf:s1:abc") == [("ulf", "s1", 3)]


async def test_seed_applies_per_code_limit(fresh_db):
    n = await seed_codes_from_env(fresh_db, "ulf:s1:unlimited,anna:s2:5,bob:s3")
    assert n == 3
    assert (await fresh_db.get_code("s1"))["quick_check_limit"] is None
    assert (await fresh_db.get_code("s2"))["quick_check_limit"] == 5
    assert (await fresh_db.get_code("s3"))["quick_check_limit"] == 3
