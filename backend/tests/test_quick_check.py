"""Tests for Quick Check (Phase Q): codes quota columns, env parsing/seeding,
and the POST /api/quick-check endpoint."""

import pytest

import backend.state as state
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


# ---------------------------------------------------------------------------
# Endpoint: POST /api/quick-check
# ---------------------------------------------------------------------------

async def test_quick_check_happy_path(client, mock_fact_checker, monkeypatch):
    monkeypatch.setattr("backend.routers.quick_check.get_fact_checker", lambda: mock_fact_checker)

    res = await client.post("/api/quick-check", json={"claim": "Die Inflation lag 2024 bei 2 Prozent."})

    assert res.status_code == 200
    body = res.json()
    fc = body["fact_check"]
    assert fc["behauptung"] == "Test claim statement"  # from mock_fact_check_response.original_claim
    assert fc["consistency"] == "hoch"
    assert fc["id"] > 0
    assert body["limit"] == 3
    assert body["remaining"] == 2
    # persisted under quick-<code> and counted
    stored = await state.get_db().get_fact_checks(session_id="quick-test-code")
    assert len(stored) == 1
    assert (await state.get_db().get_code("test-code"))["quick_checks_used"] == 1


async def test_quick_check_requires_code(no_auth_client):
    res = await no_auth_client.post("/api/quick-check", json={"claim": "x" * 10})
    assert res.status_code == 401


async def test_quick_check_invalid_code(no_auth_client):
    res = await no_auth_client.post(
        "/api/quick-check",
        json={"claim": "x" * 10},
        headers={"X-Access-Code": "nope"},
    )
    assert res.status_code == 403


async def test_quick_check_empty_claim_is_422_and_no_increment(client):
    res = await client.post("/api/quick-check", json={"claim": "   "})
    assert res.status_code == 422
    assert (await state.get_db().get_code("test-code"))["quick_checks_used"] == 0


async def test_quick_check_oversized_claim_is_422(client):
    res = await client.post("/api/quick-check", json={"claim": "x" * 1001})
    assert res.status_code == 422


async def test_quick_check_quota_exhausted_returns_429(client, mock_fact_checker, monkeypatch):
    monkeypatch.setattr("backend.routers.quick_check.get_fact_checker", lambda: mock_fact_checker)
    db = state.get_db()
    # test-code default limit is 3; push used to 3
    for _ in range(3):
        await db.increment_quick_checks("test-code")

    res = await client.post("/api/quick-check", json={"claim": "Eine Behauptung."})
    assert res.status_code == 429
    # no extra row, counter unchanged
    assert await db.get_fact_checks(session_id="quick-test-code") == []
    assert (await db.get_code("test-code"))["quick_checks_used"] == 3


async def test_quick_check_owner_unlimited_never_blocked(client, mock_fact_checker, monkeypatch):
    monkeypatch.setattr("backend.routers.quick_check.get_fact_checker", lambda: mock_fact_checker)
    db = state.get_db()
    # Re-seed test-code as unlimited by replacing it.
    await db.db.execute("UPDATE codes SET quick_check_limit = NULL, quick_checks_used = 99 WHERE code = 'test-code'")
    await db.db.commit()

    res = await client.post("/api/quick-check", json={"claim": "Noch eine Behauptung."})
    assert res.status_code == 200
    assert res.json()["remaining"] is None
    assert res.json()["limit"] is None
