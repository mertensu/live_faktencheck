"""Seeding legacy EPISODES into the sessions table."""
import pytest
from backend.database import Database
from backend.app import seed_legacy_episodes
from config import EPISODES


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


async def test_seed_inserts_all_episodes(db):
    await seed_legacy_episodes(db)
    sessions = await db.list_sessions()
    assert len(sessions) == len(EPISODES)
    one = await db.get_session("maischberger-2025-09-19")
    assert one is not None
    assert one["visibility"] == "public"


async def test_seed_is_idempotent(db):
    await seed_legacy_episodes(db)
    await seed_legacy_episodes(db)
    sessions = await db.list_sessions()
    assert len(sessions) == len(EPISODES)
