"""Tests for Live-Audio-Limits (Phase 3b): per-code audio-seconds budget."""

import pytest

from backend.auth import live_audio_limit_seconds, seed_codes_from_env
from backend.database import Database


@pytest.fixture
async def fresh_db():
    db = Database(":memory:")
    await db.connect()
    yield db
    await db.close()


# --- DB layer: codes audio columns ---

async def test_add_code_sets_default_audio_limit(fresh_db):
    await fresh_db.add_code("c1", "ann")
    row = await fresh_db.get_code("c1")
    assert row["audio_seconds_used"] == 0
    assert row["audio_seconds_limit"] == 300


async def test_add_code_accepts_explicit_audio_limit(fresh_db):
    await fresh_db.add_code("c2", "max", audio_seconds_limit=600)
    assert (await fresh_db.get_code("c2"))["audio_seconds_limit"] == 600


async def test_add_code_audio_limit_none_is_unlimited(fresh_db):
    await fresh_db.add_code("c3", "owner", audio_seconds_limit=None)
    assert (await fresh_db.get_code("c3"))["audio_seconds_limit"] is None


async def test_increment_audio_seconds_accumulates(fresh_db):
    await fresh_db.add_code("c4", "ann")
    await fresh_db.increment_audio_seconds("c4", 42)
    await fresh_db.increment_audio_seconds("c4", 8)
    assert (await fresh_db.get_code("c4"))["audio_seconds_used"] == 50


# --- Env-derived seeding ---


def test_live_audio_limit_seconds_default(monkeypatch):
    monkeypatch.delenv("LIVE_AUDIO_LIMIT_MINUTES", raising=False)
    assert live_audio_limit_seconds() == 300


def test_live_audio_limit_seconds_from_env(monkeypatch):
    monkeypatch.setenv("LIVE_AUDIO_LIMIT_MINUTES", "10")
    assert live_audio_limit_seconds() == 600


async def test_seed_sets_audio_limit_from_env(fresh_db, monkeypatch):
    monkeypatch.setenv("LIVE_AUDIO_LIMIT_MINUTES", "2")
    await seed_codes_from_env(fresh_db, "ann:s1")
    assert (await fresh_db.get_code("s1"))["audio_seconds_limit"] == 120


async def test_seed_unlimited_code_has_null_audio_limit(fresh_db, monkeypatch):
    monkeypatch.setenv("LIVE_AUDIO_LIMIT_MINUTES", "5")
    await seed_codes_from_env(fresh_db, "owner:o1:unlimited")
    row = await fresh_db.get_code("o1")
    assert row["quick_check_limit"] is None
    assert row["audio_seconds_limit"] is None
