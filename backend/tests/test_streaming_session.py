"""
Tests for StreamingSession windowing + autopilot pipeline (SG-3).

The AssemblyAI wiring (start/feed/stop transport) is out of scope here; these tests
drive handle_turn() directly with synthetic turns and mocked gate + fast_checker,
against a real in-memory DB, and assert the placeholder-then-update row sequence.
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.database import Database
from backend.services.claim_extraction import ExtractedClaim
from backend.services.gate import GatedClaim
from backend.services.streaming import StreamingSession, SPEAKER_RESOLVE_MIN_TURNS


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

    async def test_speaker_map_applied_to_claim(self, db):
        """A resolved label->name mapping is applied to the stored claim's speaker."""
        async def resolver(transcript, guests, conversation_type=""):
            return {"A": "Katharina Reiche"}

        gate = _gate([[ExtractedClaim(name="A", claim="Behauptung A.")]])
        session = StreamingSession("s1", gate, _fast_checker(), db,
                                   guests=["Katharina Reiche (CDU)"], resolve_speakers=resolver)
        session._transcript_log = ["A: etwas", "B: anderes"]
        await session._resolve_speakers()
        assert session._speaker_map == {"A": "Katharina Reiche"}

        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True, speaker_label="A")
        await session.stop()
        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == "Katharina Reiche"

    async def test_resolution_triggers_after_min_turns(self, db):
        calls = {"n": 0}

        async def resolver(transcript, guests, conversation_type=""):
            calls["n"] += 1
            return {"A": "Reiche"}

        gate = _gate([[]] * 20)
        session = StreamingSession("s1", gate, _fast_checker(), db,
                                   guests=["Reiche"], resolve_speakers=resolver)
        for i in range(SPEAKER_RESOLVE_MIN_TURNS):
            await session.handle_turn("Satz eins. Satz zwei.", end_of_turn=True, speaker_label="A")
        await session.stop()
        assert calls["n"] >= 1
        assert session._speaker_map.get("A") == "Reiche"

    async def test_no_resolution_without_guests(self, db):
        """The resolver needs candidate names; with no guests it must never run."""
        calls = {"n": 0}

        async def resolver(transcript, guests, conversation_type=""):
            calls["n"] += 1
            return {}

        gate = _gate([[]] * 20)
        session = StreamingSession("s1", gate, _fast_checker(), db,
                                   guests=[], resolve_speakers=resolver)
        for i in range(SPEAKER_RESOLVE_MIN_TURNS + 2):
            await session.handle_turn("Satz eins. Satz zwei.", end_of_turn=True, speaker_label="A")
        await session.stop()
        assert calls["n"] == 0

    async def test_speaker_revision_rewrites_stored_claim(self, db):
        """A SpeakerRevision for a claim's turn rewrites its stored speaker + emits an event."""
        events = []

        async def on_event(e):
            events.append(e)

        gate = _gate([[GatedClaim(name="A", claim="Behauptung A.", source="Behauptung A.")]])
        session = StreamingSession("s1", gate, _fast_checker(), db, on_event=on_event)
        # Turn 0 gates a claim; its source sentence ties it back to the turn.
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        # Drain the background check task so the row exists and is tied to its turn.
        await asyncio.gather(*list(session._tasks))
        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == "A"

        # Reclustering corrects turn 0's speaker A -> B.
        await session.handle_speaker_revision([{"turn_order": 0, "speaker_label": "B"}])
        await session.stop()

        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == "B"
        assert any(e["type"] == "claim_speaker_update" and e["speaker"] == "B" for e in events)

    async def test_speaker_revision_uses_resolved_name(self, db):
        """When a name is already resolved, a revision rewrites to the real name, not the label."""
        gate = _gate([[GatedClaim(name="A", claim="Behauptung A.", source="Behauptung A.")]])
        session = StreamingSession("s1", gate, _fast_checker(), db)
        session._speaker_map = {"B": "Katharina Reiche"}
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await asyncio.gather(*list(session._tasks))
        await session.handle_speaker_revision([{"turn_order": 0, "speaker_label": "B"}])
        await session.stop()
        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == "Katharina Reiche"

    async def test_late_resolution_rewrites_stored_claim(self, db):
        """A claim stored under a bare label is rewritten when resolution later names it."""
        events = []

        async def on_event(e):
            events.append(e)

        async def resolver(transcript, guests, conversation_type=""):
            return {"B": "Connemann"}

        gate = _gate([[GatedClaim(name="B", claim="Behauptung B.", source="Behauptung B.")]])
        session = StreamingSession("s1", gate, _fast_checker(), db, on_event=on_event,
                                   guests=["Connemann"], resolve_speakers=resolver)
        # Claim gated + stored before any resolution -> speaker is the bare label "B".
        await session.handle_turn("Behauptung B. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="B", turn_order=0)
        await asyncio.gather(*list(session._tasks))
        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == "B"

        # Resolution lands -> the stored claim is rewritten to the real name + UI notified.
        session._transcript_log = ["B: etwas", "A: anderes"]
        await session._resolve_speakers()
        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == "Connemann"
        assert any(e["type"] == "claim_speaker_update" and e["speaker"] == "Connemann" for e in events)

    async def test_revision_for_unknown_turn_is_noop(self, db):
        gate = _gate([[]])
        session = StreamingSession("s1", gate, _fast_checker(), db)
        await session.handle_speaker_revision([{"turn_order": 99, "speaker_label": "B"}])
        await session.stop()
        assert await db.get_fact_checks(session_id="s1") == []

    async def test_max_speakers_derives_from_guests(self, db):
        session = StreamingSession("s1", _gate([[]]), _fast_checker(), db,
                                   guests=["Reiche", "Dröge"])
        assert session._max_speakers() == 3  # 2 guests + moderator
        no_guests = StreamingSession("s2", _gate([[]]), _fast_checker(), db, guests=[])
        assert no_guests._max_speakers() is None

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
