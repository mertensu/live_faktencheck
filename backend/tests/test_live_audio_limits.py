"""Tests for Live-Audio-Limits (Phase 3b): per-code audio-seconds budget."""

import pytest

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
