"""Tests for Live-Audio-Limits (Phase 3b): per-code audio-seconds budget."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import backend.state as state
from backend.auth import live_audio_limit_seconds, seed_codes_from_env
from backend.database import Database
from backend.tests.conftest import TEST_ACCESS_CODE


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


# --- Endpoint guards on POST /api/audio-block ---


def _audio_form():
    return {"audio": ("block.webm", b"x" * 1000, "audio/webm")}, {"session_id": "s-ep"}


async def _set_code_budget(used: int, limit):
    await state.db.db.execute(
        "UPDATE codes SET audio_seconds_used = ?, audio_seconds_limit = ? WHERE code = ?",
        (used, limit, TEST_ACCESS_CODE),
    )
    await state.db.db.commit()


async def test_audio_block_429_when_budget_exhausted(client):
    await _set_code_budget(used=300, limit=300)
    files, data = _audio_form()
    with patch("backend.routers.audio.get_transcription_service") as mock_get:
        res = await client.post("/api/audio-block", files=files, data=data)
        assert res.status_code == 429
        mock_get.assert_not_called()


async def test_audio_block_413_when_block_too_large(client):
    await _set_code_budget(used=0, limit=300)
    big = {"audio": ("block.webm", b"y" * 50, "audio/webm")}
    with patch("backend.routers.audio.MAX_AUDIO_BLOCK_BYTES", 10), \
         patch("backend.routers.audio.get_transcription_service") as mock_get:
        res = await client.post("/api/audio-block", files=big, data={"session_id": "s-ep"})
        assert res.status_code == 413
        mock_get.assert_not_called()


async def test_audio_block_passes_and_reports_remaining(client):
    await _set_code_budget(used=60, limit=300)
    files, data = _audio_form()

    mock_tx = MagicMock()
    mock_tx.transcribe = MagicMock(return_value=("Sprecher A: hi", 30.0))
    mock_ex = MagicMock()
    mock_ex.resolve_labels_async = AsyncMock(return_value="Anna: hi")
    mock_ex.extract_claims_async = AsyncMock(return_value=[])

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_tx), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_ex):
        res = await client.post("/api/audio-block", files=files, data=data)

    assert res.status_code == 202
    assert res.json()["remaining_seconds"] == 240
    assert (await state.db.get_code(TEST_ACCESS_CODE))["audio_seconds_used"] == 90


async def test_audio_block_unlimited_code_bypasses_budget(client):
    await _set_code_budget(used=99999, limit=None)
    files, data = _audio_form()
    mock_tx = MagicMock()
    mock_tx.transcribe = MagicMock(return_value=("Sprecher A: hi", 10.0))
    mock_ex = MagicMock()
    mock_ex.resolve_labels_async = AsyncMock(return_value="Anna: hi")
    mock_ex.extract_claims_async = AsyncMock(return_value=[])
    with patch("backend.routers.audio.get_transcription_service", return_value=mock_tx), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_ex):
        res = await client.post("/api/audio-block", files=files, data=data)
    assert res.status_code == 202
    assert res.json()["remaining_seconds"] is None


async def test_audio_block_overshoot_then_blocks(client):
    await _set_code_budget(used=295, limit=300)
    files, data = _audio_form()
    mock_tx = MagicMock()
    mock_tx.transcribe = MagicMock(return_value=("Sprecher A: hi", 30.0))
    mock_ex = MagicMock()
    mock_ex.resolve_labels_async = AsyncMock(return_value="Anna: hi")
    mock_ex.extract_claims_async = AsyncMock(return_value=[])
    with patch("backend.routers.audio.get_transcription_service", return_value=mock_tx), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_ex):
        first = await client.post("/api/audio-block", files=files, data=data)
        assert first.status_code == 202
    assert (await state.db.get_code(TEST_ACCESS_CODE))["audio_seconds_used"] == 325
    second = await client.post("/api/audio-block", files=_audio_form()[0], data={"session_id": "s-ep"})
    assert second.status_code == 429
