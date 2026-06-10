"""Tests for the minimal access gate (Phase 3a): codes table, env seeding,
require_code dependency, and endpoint gating."""

import pytest

from backend.database import Database
from backend.auth import parse_access_codes, seed_codes_from_env
from backend.tests.conftest import TEST_ACCESS_CODE


# =============================================================================
# DB layer: codes table
# =============================================================================

@pytest.fixture
async def fresh_db():
    db = Database(":memory:")
    await db.connect()
    yield db
    await db.close()


async def test_get_code_returns_active_row(fresh_db):
    await fresh_db.add_code("secret1", "ulf")
    row = await fresh_db.get_code("secret1")
    assert row is not None
    assert row["code"] == "secret1"
    assert row["name"] == "ulf"
    assert row["active"] == 1


async def test_get_code_unknown_returns_none(fresh_db):
    assert await fresh_db.get_code("nope") is None


async def test_deactivated_code_is_not_returned(fresh_db):
    await fresh_db.add_code("secret1", "ulf")
    assert await fresh_db.deactivate_code("secret1") is True
    assert await fresh_db.get_code("secret1") is None


async def test_count_and_list_codes(fresh_db):
    assert await fresh_db.count_codes() == 0
    await fresh_db.add_code("a", "ann")
    await fresh_db.add_code("b", "max")
    assert await fresh_db.count_codes() == 2
    names = {c["name"] for c in await fresh_db.list_codes()}
    assert names == {"ann", "max"}


# =============================================================================
# Env parsing + fail-closed seeding
# =============================================================================

def test_parse_access_codes_basic():
    assert parse_access_codes("ulf:s1,anna:s2") == [("ulf", "s1"), ("anna", "s2")]


def test_parse_access_codes_ignores_malformed_and_whitespace():
    assert parse_access_codes(" ulf : s1 , broken , :x , y: ,anna:s2") == [
        ("ulf", "s1"),
        ("anna", "s2"),
    ]


def test_parse_access_codes_empty():
    assert parse_access_codes("") == []
    assert parse_access_codes(None) == []


async def test_seed_codes_from_env_inserts_when_empty(fresh_db):
    n = await seed_codes_from_env(fresh_db, "ulf:s1,anna:s2")
    assert n == 2
    assert (await fresh_db.get_code("s1"))["name"] == "ulf"


async def test_seed_codes_is_idempotent_when_table_nonempty(fresh_db):
    await fresh_db.add_code("existing", "someone")
    n = await seed_codes_from_env(fresh_db, "ulf:s1")
    assert n == 0
    assert await fresh_db.get_code("s1") is None  # not re-seeded over existing codes


async def test_seed_codes_empty_env_leaves_table_empty(fresh_db):
    assert await seed_codes_from_env(fresh_db, None) == 0
    assert await fresh_db.count_codes() == 0


# =============================================================================
# require_code dependency via endpoints
# =============================================================================

async def test_create_session_without_code_is_401(no_auth_client):
    resp = await no_auth_client.post("/api/sessions", json={"title": "T"})
    assert resp.status_code == 401


async def test_create_session_with_invalid_code_is_403(no_auth_client):
    resp = await no_auth_client.post(
        "/api/sessions", json={"title": "T"}, headers={"X-Access-Code": "wrong"}
    )
    assert resp.status_code == 403


async def test_create_session_with_valid_code_persists_owner_code(client):
    import backend.state as state

    sid = (await client.post("/api/sessions", json={"title": "T"})).json()["session_id"]
    session = await state.get_db().get_session(sid)
    assert session["owner_code"] == TEST_ACCESS_CODE


async def test_approve_claims_without_code_is_401(no_auth_client):
    resp = await no_auth_client.post(
        "/api/approve-claims",
        json={"claims": [{"name": "A", "claim": "x"}], "session_id": "s"},
    )
    assert resp.status_code == 401


async def test_reads_stay_open_without_code(no_auth_client):
    assert (await no_auth_client.get("/api/config/shows")).status_code == 200
    assert (await no_auth_client.get("/api/health")).status_code == 200


def test_all_cost_endpoints_require_code():
    """Every endpoint that triggers a paid call or creates a session is gated."""
    from backend.app import app
    from backend.auth import require_code

    gated = {
        ("POST", "/api/sessions"),
        ("POST", "/api/audio-block"),
        ("POST", "/api/text-block"),
        ("POST", "/api/approve-claims"),
        ("POST", "/api/fact-checks/resend"),
        ("PUT", "/api/fact-checks/{fact_check_id}"),
        ("POST", "/api/pipeline-status/{block_id}/retrigger"),
    }
    found = set()
    for route in app.routes:
        deps = getattr(getattr(route, "dependant", None), "dependencies", [])
        if any(d.call is require_code for d in deps):
            for method in route.methods:
                found.add((method, route.path))
    missing = gated - found
    assert not missing, f"endpoints missing require_code: {missing}"
