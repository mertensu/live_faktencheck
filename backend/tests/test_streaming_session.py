"""
Tests for StreamingSession windowing + autopilot pipeline (SG-3).

The AssemblyAI wiring (start/feed/stop transport) is out of scope here; these tests
drive handle_turn() directly with synthetic turns and mocked gate + fast_checker,
against a real in-memory DB, and assert the placeholder-then-update row sequence.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.database import Database
from backend.services.claim_extraction import ExtractedClaim
from backend.services.streaming import StreamingSession


@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


def _gate(claims_per_flush):
    """A ClaimGate stub whose .gate() returns the given claims once, then nothing."""
    calls = {"n": 0}

    async def gate(window_text, guests, **kw):
        i = calls["n"]
        calls["n"] += 1
        return claims_per_flush[i] if i < len(claims_per_flush) else []

    stub = MagicMock()
    stub.gate = AsyncMock(side_effect=gate)
    return stub


def _fast_checker(consistency="hoch"):
    async def check(speaker, claim, context=None, episode_date=None):
        return {
            "speaker": speaker, "original_claim": claim, "consistency": consistency,
            "evidence": "Ein kurzer Satz.", "sources": [],
            "double_check": False, "critique_note": "",
        }
    stub = MagicMock()
    stub.check_claim_async = AsyncMock(side_effect=check)
    return stub


class TestWindowing:
    async def test_flush_on_two_sentences(self, db):
        gate = _gate([[ExtractedClaim(name="A", claim="Behauptung A.")]])
        session = StreamingSession("s1", gate, _fast_checker(), db)
        # One finalized turn with two sentences -> should flush immediately.
        await session.handle_turn("Erster Satz. Zweiter Satz.", end_of_turn=True, speaker_label="A")
        await session.stop()
        assert gate.gate.await_count >= 1

    async def test_partial_turns_do_not_flush(self, db):
        gate = _gate([[]])
        session = StreamingSession("s1", gate, _fast_checker(), db)
        await session.handle_turn("Ein unfertiger", end_of_turn=False)
        assert gate.gate.await_count == 0  # partials never gate
        await session.stop()

    async def test_placeholder_then_update_with_fast_depth(self, db):
        gate = _gate([[ExtractedClaim(name="Julia", claim="Deutschland hat 83 Mio. Einwohner.")]])
        session = StreamingSession("s1", gate, _fast_checker(consistency="hoch"), db)
        await session.handle_turn("Deutschland hat 83 Millionen Einwohner. Das ist viel.",
                                  end_of_turn=True, speaker_label="Julia")
        await session.stop()  # drains background check tasks

        rows = await db.get_fact_checks(session_id="s1")
        assert len(rows) == 1
        row = rows[0]
        assert row["check_depth"] == "fast"
        assert row["consistency"] == "hoch"
        assert row["status"] == ""          # placeholder 'processing' was updated away
        assert row["sprecher"] == "Julia"
        assert row["begruendung"] == "Ein kurzer Satz."

    async def test_empty_gate_writes_no_rows(self, db):
        gate = _gate([[]])
        session = StreamingSession("s1", gate, _fast_checker(), db)
        await session.handle_turn("Guten Abend. Schön hier zu sein.", end_of_turn=True, speaker_label="Mod")
        await session.stop()
        assert await db.get_fact_checks(session_id="s1") == []

    async def test_events_emitted(self, db):
        events = []

        async def on_event(e):
            events.append(e)

        gate = _gate([[ExtractedClaim(name="A", claim="Behauptung A.")]])
        session = StreamingSession("s1", gate, _fast_checker(), db, on_event=on_event)
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True, speaker_label="A")
        await session.stop()

        types = [e["type"] for e in events]
        assert "turn" in types
        assert "claim_processing" in types
        assert "claim_result" in types
