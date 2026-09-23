"""
Tests for StreamingSession windowing + autopilot pipeline (SG-3).

The AssemblyAI wiring (start/feed/stop transport) is out of scope here; these tests
drive handle_turn() directly with synthetic turns and mocked gate + fast_checker,
against a real in-memory DB, and assert the placeholder-then-update row sequence.
"""

import asyncio
import threading

import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.database import Database
from backend.services.claim_extraction import ExtractedClaim
from backend.services import streaming as streaming_mod
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


class TestTurnWords:
    async def test_words_carried_on_buffer_and_turn(self, db):
        session = StreamingSession("s1", _gate([[]]), _fast_checker(), db)
        words = [{"text": "Hallo", "start": 0, "end": 400}]
        await session.handle_turn("Hallo", end_of_turn=True, speaker_label="A",
                                  turn_order=0, words=words)
        assert session._buffer[0]["words"] == words
        assert session._turns[0]["words"] == words
        await session.stop()

    async def test_reemitted_final_replaces_words(self, db):
        """A repeated final with changed text carries the new words, not stale ones."""
        session = StreamingSession("s1", _gate([[]]), _fast_checker(), db)
        await session.handle_turn("Hallo", end_of_turn=True, speaker_label="A", turn_order=0,
                                  words=[{"text": "Hallo", "start": 0, "end": 400}])
        new_words = [{"text": "Hallo", "start": 0, "end": 400},
                     {"text": "Welt", "start": 450, "end": 800}]
        await session.handle_turn("Hallo Welt", end_of_turn=True, speaker_label="A",
                                  turn_order=0, words=new_words)
        assert len(session._buffer) == 1
        assert session._buffer[0]["text"] == "Hallo Welt"
        assert session._buffer[0]["words"] == new_words
        assert session._turns[0]["words"] == new_words
        await session.stop()


# ---- voiceprint speaker ID (docs/speaker-id-integration-plan.md §10) ---------------------
# The SpeakerIdentifier is a stub (identify(pcm, sr) -> (name, score)); no onnxruntime.

SR = 16000


def _ident(result=("Alice", 0.8), voiceprints=("Alice", "Bob")):
    stub = MagicMock()
    stub.identify = MagicMock(return_value=result)
    stub.voiceprints = {n: None for n in voiceprints}
    return stub


def _pcm_bytes(ms, loud=True):
    n = SR * ms // 1000
    rng = np.random.default_rng(0)
    samples = rng.integers(-8000, 8000, n) if loud else np.zeros(n, dtype=np.int64)
    return samples.astype("<i2").tobytes()


class _FakeClient:
    def __init__(self):
        self.sent = 0

    async def stream(self, audio):
        self.sent += len(audio)

    async def disconnect(self):
        pass


async def _drain(session):
    while session._tasks:
        await asyncio.gather(*list(session._tasks))


class TestClassifier:
    async def test_feed_advances_clock_only_when_sent(self, db):
        session = StreamingSession("s1", _gate([]), _fast_checker(), db, speaker_identifier=_ident())
        await session.feed(_pcm_bytes(1000))  # no client -> dropped for both
        assert session._samples == 0
        session._client = _FakeClient()
        await session.feed(_pcm_bytes(1000))
        assert session._samples == SR
        await session.stop()

    async def test_ring_buffer_is_bounded(self, db, monkeypatch):
        monkeypatch.setattr(streaming_mod, "SPEAKER_ID_BUFFER_MS", 4000)
        session = StreamingSession("s1", _gate([]), _fast_checker(), db, speaker_identifier=_ident())
        session._client = _FakeClient()
        for _ in range(10):
            await session.feed(_pcm_bytes(1000))
        assert len(session._pcm) == 4 * SR * 2
        assert session._samples == 10 * SR
        await session.stop()

    async def test_loud_window_is_classified_into_track(self, db):
        ident = _ident(("Alice", 0.8))
        session = StreamingSession("s1", _gate([]), _fast_checker(), db, speaker_identifier=ident)
        session._client = _FakeClient()
        await session.feed(_pcm_bytes(4000))
        assert session._classify_tick()
        await _drain(session)
        assert session._spk_track.entries == [(1000, 4000, "Alice", 0.8)]
        assert session._spk_track.covered_ms == 4000
        await session.stop()

    async def test_silent_window_skips_identify(self, db):
        ident = _ident()
        session = StreamingSession("s1", _gate([]), _fast_checker(), db, speaker_identifier=ident)
        session._client = _FakeClient()
        await session.feed(_pcm_bytes(3000, loud=False))
        session._classify_tick()
        await _drain(session)
        assert session._spk_track.entries == [(0, 3000, None, None)]
        ident.identify.assert_not_called()
        await session.stop()

    async def test_slow_identify_makes_next_tick_skip(self, db):
        release = threading.Event()

        def slow(pcm, sr):
            release.wait(2)
            return "Alice", 0.8

        ident = _ident()
        ident.identify.side_effect = slow
        session = StreamingSession("s1", _gate([]), _fast_checker(), db, speaker_identifier=ident)
        session._client = _FakeClient()
        await session.feed(_pcm_bytes(3000))
        assert session._classify_tick()
        await session.feed(_pcm_bytes(1000))
        assert not session._classify_tick()  # previous step still running -> dropped
        release.set()
        await _drain(session)
        assert ident.identify.call_count == 1
        assert session._classify_tick()  # free again, new audio available
        await session.stop()


TURN = "Behauptung A. Noch ein Satz."
TURN_WORDS = [{"text": w, "start": i * 400, "end": i * 400 + 350}
              for i, w in enumerate(["behauptung", "a", "noch", "ein", "satz"])]  # 0..1950 ms


@pytest.fixture
def logfire_calls(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(streaming_mod, "logfire", fake)
    return fake.info


def _vp_session(db, ident=None, events=None, **kw):
    async def on_event(e):
        events.append(e)

    gate = _gate([[GatedClaim(name="A", claim="Behauptung A.", source="Behauptung A.")]])
    checker = _fast_checker()
    session = StreamingSession("s1", gate, checker, db, speaker_identifier=ident or _ident(),
                               on_event=on_event if events is not None else None, **kw)
    return session, checker


async def _turn(session, label="A", turn_order=0):
    await session.handle_turn(TURN, end_of_turn=True, speaker_label=label,
                              turn_order=turn_order, words=TURN_WORDS)


@pytest.mark.usefixtures("logfire_calls")
class TestVoiceprintClaims:
    async def test_covered_span_names_claim_before_check(self, db):
        session, checker = _vp_session(db)
        session._spk_track.add(0, 3000, "Alice", 0.8)
        await _turn(session)
        await _drain(session)
        assert checker.check_claim_async.await_args.kwargs["speaker"] == "Alice"
        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == "Alice"
        assert session._turn_claims == {} and session._label_claims == {}
        await session.stop()

    async def test_no_voiceprint_verdict_keeps_label(self, db):
        session, checker = _vp_session(db)
        session._spk_track.add(0, 3000, "Alice", 0.8)
        session._spk_track.add(0, 3000, "Bob", 0.8)  # mixed -> no clear majority
        await _turn(session)
        await _drain(session)
        assert checker.check_claim_async.await_args.kwargs["speaker"] == "A"
        pid = (await db.get_fact_checks(session_id="s1"))[0]["id"]
        assert session._label_claims == {"A": [pid]}
        assert session._turn_claims == {0: [(pid, "A")]}
        await session.stop()

    async def test_coverage_within_timeout(self, db):
        session, checker = _vp_session(db)
        session._client = _FakeClient()
        await session.feed(_pcm_bytes(2500))  # < one window: nothing to classify yet
        await _turn(session)

        async def later():
            await asyncio.sleep(0.05)
            await session.feed(_pcm_bytes(1000))
            session._classify_tick()

        await asyncio.gather(later(), _drain(session))
        await _drain(session)
        assert checker.check_claim_async.await_args.kwargs["speaker"] == "Alice"
        await session.stop()

    async def test_timeout_falls_back_then_late_rewrite(self, db, monkeypatch):
        monkeypatch.setattr(streaming_mod, "SPEAKER_ID_WAIT_MS", 20)
        events = []
        session, checker = _vp_session(db, events=events)
        session._client = _FakeClient()
        await _turn(session)
        await _drain(session)
        assert checker.check_claim_async.await_args.kwargs["speaker"] == "A"
        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == "A" and len(session._pending_spk) == 1

        await session.feed(_pcm_bytes(3000))
        session._classify_tick()
        await _drain(session)
        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == "Alice"
        assert {"type": "claim_speaker_update", "id": rows[0]["id"], "speaker": "Alice"} in events
        assert session._pending_spk == []
        # Locked: no longer on the label paths.
        assert session._label_claims == {"A": []}
        await session.stop()

    async def test_late_rewrite_survives_running_check(self, db, monkeypatch):
        """A rewrite during the check is not clobbered by the checker's echoed speaker."""
        monkeypatch.setattr(streaming_mod, "SPEAKER_ID_WAIT_MS", 0)
        session, checker = _vp_session(db)
        gate_open = asyncio.Event()
        orig = checker.check_claim_async.side_effect

        async def slow_check(**kw):
            await gate_open.wait()
            return await orig(**kw)

        checker.check_claim_async.side_effect = slow_check
        await _turn(session)
        await asyncio.sleep(0.01)  # placeholder stored, check pending
        session._spk_track.add(0, 3000, "Alice", 0.8)
        await session._resolve_pending_spk()
        gate_open.set()
        await _drain(session)
        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == "Alice" and rows[0]["status"] == ""
        await session.stop()

    async def test_revision_does_not_overwrite_voiceprint_name(self, db):
        session, _ = _vp_session(db)
        session._spk_track.add(0, 3000, "Alice", 0.8)
        await _turn(session)
        await _drain(session)
        await session.handle_speaker_revision([{"turn_order": 0, "speaker_label": "B"}])
        await session._apply_map_to_pending({"A": "Bob"})
        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == "Alice"
        await session.stop()

    async def test_second_guard_skips_voiceprint_pids(self, db):
        """Even if a locked pid sits on a label path, both rewrites skip it."""
        session, _ = _vp_session(db)
        session._spk_track.add(0, 3000, "Alice", 0.8)
        await _turn(session)
        await _drain(session)
        pid = (await db.get_fact_checks(session_id="s1"))[0]["id"]
        session._turn_claims[0] = [(pid, "A")]
        session._label_claims["A"] = [pid]
        await session.handle_speaker_revision([{"turn_order": 0, "speaker_label": "B"}])
        await session._apply_map_to_pending({"A": "Bob"})
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Alice"
        await session.stop()

    async def test_no_voiceprint_verdict_label_paths_still_rewrite(self, db):
        session, _ = _vp_session(db)
        session._spk_track.add(0, 3000, None, 0.45)  # unsure, not unknown
        await _turn(session)
        await _drain(session)
        await session.handle_speaker_revision([{"turn_order": 0, "speaker_label": "B"}])
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "B"
        await session.stop()

    async def test_unknown_voice(self, db):
        events = []
        session, checker = _vp_session(db, events=events)
        session._spk_track.add(0, 3000, None, 0.2)
        session._spk_track.add(500, 3500, None, 0.25)
        await _turn(session)
        await _drain(session)
        assert checker.check_claim_async.await_args.kwargs["speaker"] == streaming_mod.UNKNOWN_SPEAKER
        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == streaming_mod.UNKNOWN_SPEAKER
        proc = next(e for e in events if e["type"] == "claim_processing")
        assert proc["unknown_voice"] is True
        # No label fallback, and label paths cannot pull it back to a guest.
        await session.handle_speaker_revision([{"turn_order": 0, "speaker_label": "B"}])
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == streaming_mod.UNKNOWN_SPEAKER
        await session.stop()

    async def test_between_thresholds_uses_fallback(self, db):
        session, checker = _vp_session(db)
        session._spk_track.add(0, 3000, None, 0.2)
        session._spk_track.add(500, 3500, None, 0.45)  # overlaps the 0–750 ms span
        await _turn(session)
        await _drain(session)
        assert checker.check_claim_async.await_args.kwargs["speaker"] == "A"
        await session.stop()

    async def test_one_logfire_record_per_claim(self, db, logfire_calls):
        session, _ = _vp_session(db)
        session._spk_track.add(0, 3000, "Alice", 0.8)
        await _turn(session)
        await _drain(session)
        await session.stop()
        assert logfire_calls.call_count == 1
        kw = logfire_calls.call_args.kwargs
        assert kw["speaker"] == "Alice" and kw["source"] == "span"
        assert kw["voiceprint_name"] == "Alice" and kw["score"] == 0.8
        assert kw["span"] == [0, 750] and kw["session_id"] == "s1"
        assert "waited_ms" in kw

    async def test_pending_claim_logged_once_on_give_up(self, db, logfire_calls, monkeypatch):
        monkeypatch.setattr(streaming_mod, "SPEAKER_ID_WAIT_MS", 0)
        session, _ = _vp_session(db)
        await _turn(session)
        await _drain(session)
        assert logfire_calls.call_count == 0  # still pending
        await session.stop()  # no audio ever arrives -> give up
        assert logfire_calls.call_count == 1
        assert logfire_calls.call_args.kwargs["source"] == "label"

    async def test_disabled_speaker_id_logs_nothing(self, db, logfire_calls):
        gate = _gate([[GatedClaim(name="A", claim="Behauptung A.", source="Behauptung A.")]])
        session = StreamingSession("s1", gate, _fast_checker(), db)
        await _turn(session)
        await session.stop()
        logfire_calls.assert_not_called()


def _words_at(start_ms):
    return [{"text": "satz", "start": start_ms, "end": start_ms + 1000},
            {"text": "eins", "start": start_ms + 1000, "end": start_ms + 2000}]


async def _voted_turn(session, turn_order, label, name):
    """A finalized turn at its own time slot, with the track naming it ``name``."""
    t = turn_order * 5000
    session._spk_track.add(t, t + 3000, name, 0.8)
    await session.handle_turn(f"Satz {turn_order}.", end_of_turn=True, speaker_label=label,
                              turn_order=turn_order, words=_words_at(t))


@pytest.mark.usefixtures("logfire_calls")
class TestLabelNaming:
    async def test_consistent_votes_name_label_and_rewrite_pending(self, db):
        events = []

        async def on_event(e):
            events.append(e)

        gate = _gate([[GatedClaim(name="A", claim="Behauptung A.", source="Behauptung A.")]])
        session = StreamingSession("s1", gate, _fast_checker(), db, on_event=on_event,
                                   speaker_identifier=_ident())
        # A claim with no word timestamps -> no span -> stored under the bare label.
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await _drain(session)
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "A"

        for i in range(1, 1 + streaming_mod.SPEAKER_ID_LABEL_MIN_VOTES):
            await _voted_turn(session, i, "A", "Alice")
        assert session._speaker_map == {"A": "Alice"}
        assert session._map_source == {"A": "label_vote"}
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Alice"
        assert any(e["type"] == "claim_speaker_update" and e["speaker"] == "Alice" for e in events)
        await session.stop()

    async def test_turn_named_by_voiceprint_and_label_renamed(self, db):
        events = []

        async def on_event(e):
            events.append(e)

        session = StreamingSession("s1", _gate([]), _fast_checker(), db, on_event=on_event,
                                   speaker_identifier=_ident())
        await _voted_turn(session, 0, "B", "Connemann")
        turn = next(e for e in events if e["type"] == "turn")
        assert turn["turn_order"] == 0 and turn["label"] == "B"
        assert {"type": "turn_speaker_update", "turn_order": 0, "speaker": "Connemann"} in events
        for i in range(1, streaming_mod.SPEAKER_ID_LABEL_MIN_VOTES):
            await _voted_turn(session, i, "B", "Connemann")
        assert {"type": "speaker_map_update", "label": "B", "speaker": "Connemann"} in events
        await session.stop()

    async def test_mixed_votes_no_mapping(self, db):
        session = StreamingSession("s1", _gate([]), _fast_checker(), db, speaker_identifier=_ident())
        for i, name in enumerate(["Alice", "Bob", "Alice", "Bob"]):
            await _voted_turn(session, i, "A", name)
        assert "A" not in session._speaker_map
        await session.stop()

    async def test_mapping_follows_reclustering(self, db):
        session = StreamingSession("s1", _gate([]), _fast_checker(), db, speaker_identifier=_ident())
        for i in range(3):
            await _voted_turn(session, i, "A", "Alice")
        for i in range(3, 7):
            await _voted_turn(session, i, "A", "Bob")
        assert session._speaker_map.get("A") != "Bob"  # 3 Alice / 4 Bob: no 80 % majority
        # AssemblyAI reclusters the Alice turns to B: A is now all Bob, B all Alice.
        await session.handle_speaker_revision(
            [{"turn_order": i, "speaker_label": "B"} for i in range(3)])
        assert session._speaker_map == {"A": "Bob", "B": "Alice"}
        await session.stop()


@pytest.mark.usefixtures("logfire_calls")
class TestLlmGating:
    async def _run(self, db, ident, speakers, preset=None):
        calls = []

        async def resolver(transcript, guests, conversation_type=""):
            calls.append(transcript)
            return {"A": "LLM-Name", "B": "Bob"}

        session = StreamingSession("s1", _gate([[]] * 20), _fast_checker(), db,
                                   guests=speakers, speakers=speakers,
                                   resolve_speakers=resolver, speaker_identifier=ident)
        if preset:
            session._speaker_map.update(preset)
            session._map_source.update({k: "label_vote" for k in preset})
        for i in range(SPEAKER_RESOLVE_MIN_TURNS):
            await session.handle_turn("Satz eins. Satz zwei.", end_of_turn=True, speaker_label="A")
        await session.stop()
        return session, calls

    async def test_all_enrolled_never_calls_llm(self, db):
        _, calls = await self._run(db, _ident(voiceprints=("Alice", "Bob")), ["Alice", "Bob"])
        assert calls == []

    async def test_missing_speaker_calls_llm_without_overwriting_voiceprint_labels(self, db):
        session, calls = await self._run(db, _ident(voiceprints=("Alice",)), ["Alice", "Bob"],
                                         preset={"A": "Alice"})
        assert session._missing == ["Bob"]
        assert len(calls) >= 1
        assert session._speaker_map == {"A": "Alice", "B": "Bob"}

    async def test_speaker_id_off_keeps_llm(self, db):
        _, calls = await self._run(db, None, ["Alice", "Bob"])
        assert len(calls) >= 1

    async def test_status_event_lists_enrolled_and_missing(self, db):
        events = []

        async def on_event(e):
            events.append(e)

        session = StreamingSession("s1", _gate([]), _fast_checker(), db, on_event=on_event,
                                   speakers=["Alice", "Bob"], speaker_identifier=_ident(voiceprints=("alice",)))
        await session._announce_speaker_id()
        assert events == [{"type": "speaker_id_status", "enrolled": ["Alice"], "missing": ["Bob"]}]


def _recording_gate():
    """A gate stub that records each window text and returns no claims."""
    windows = []

    async def gate(window_text, guests, **kw):
        windows.append(window_text)
        return []

    stub = MagicMock()
    stub.gate = AsyncMock(side_effect=gate)
    return stub, windows


class TestEarlySentences:
    async def test_settled_sentences_gate_before_end_of_turn(self, db):
        gate, windows = _recording_gate()
        session = StreamingSession("s1", gate, _fast_checker(), db)
        await session.handle_turn("Der Strom ist teuer. Die Preise steigen. Und dann", end_of_turn=False,
                                  speaker_label="B", turn_order=0)
        assert windows == ["B: Der Strom ist teuer.\nB: Die Preise steigen."]
        await session.stop()

    async def test_last_partial_sentence_is_not_taken(self, db):
        """Only a sentence followed by another one is settled; the last may still grow."""
        gate, windows = _recording_gate()
        session = StreamingSession("s1", gate, _fast_checker(), db)
        await session.handle_turn("Immer eine Überraschung.", end_of_turn=False, turn_order=0)
        assert session._buffer == []
        await session.stop()

    async def test_repeated_partial_does_not_retake(self, db):
        session = StreamingSession("s1", _recording_gate()[0], _fast_checker(), db)
        for _ in range(3):
            await session.handle_turn("Erster Satz hier. Zwei", end_of_turn=False, turn_order=0)
        assert [e["text"] for e in session._buffer] == ["Erster Satz hier."]
        await session.stop()

    async def test_final_turn_only_gates_untaken_rest(self, db):
        gate, windows = _recording_gate()
        session = StreamingSession("s1", gate, _fast_checker(), db)
        await session.handle_turn("Der Strom ist teuer. Die Preise steigen. Und", end_of_turn=False,
                                  speaker_label="B", turn_order=0)
        # Final re-renders the settled sentences slightly and completes the last one.
        await session.handle_turn("Der Strom ist teuer! Die Preise steigen. Und das seit Jahren. Punkt.",
                                  end_of_turn=True, speaker_label="B", turn_order=0)
        assert windows[-1] == "B: Und das seit Jahren. Punkt."
        # The transcript keeps the whole turn.
        assert session._turns[0]["text"].startswith("Der Strom ist teuer!")
        await session.stop()

    async def test_reemitted_final_keeps_early_entries(self, db, monkeypatch):
        monkeypatch.setattr(streaming_mod, "WINDOW_MIN_SENTENCES", 10)  # keep the window open
        monkeypatch.setattr(streaming_mod, "WINDOW_MAX_TURNS", 10)
        session = StreamingSession("s1", _recording_gate()[0], _fast_checker(), db)
        await session.handle_turn("Erster Satz hier. Zwei", end_of_turn=False, turn_order=0)
        await session.handle_turn("Erster Satz hier. Zweiter.", end_of_turn=True, turn_order=0)
        await session.handle_turn("Erster Satz hier. Zweiter Satz.", end_of_turn=True, turn_order=0)
        assert [e["text"] for e in session._buffer] == ["Erster Satz hier.", "Zweiter Satz."]
        await session.stop()

    async def test_disabled_flag_keeps_old_behaviour(self, db, monkeypatch):
        monkeypatch.setattr(streaming_mod, "STREAM_EARLY_SENTENCES", False)
        gate, windows = _recording_gate()
        session = StreamingSession("s1", gate, _fast_checker(), db)
        await session.handle_turn("Eins zwei. Drei vier. Fünf", end_of_turn=False, turn_order=0)
        assert windows == [] and session._buffer == []
        await session.stop()

    async def test_duplicate_claim_source_checked_once(self, db):
        claim = GatedClaim(name="A", claim="Der Strom ist teuer.", source="Der Strom ist teuer.")
        again = GatedClaim(name="A", claim="Strom ist teuer.", source="Der Strom ist teuer!")
        gate = _gate([[claim], [again]])
        checker = _fast_checker()
        session = StreamingSession("s1", gate, checker, db)
        await session.handle_turn("Der Strom ist teuer. Satz.", end_of_turn=True, speaker_label="A", turn_order=0)
        await session.handle_turn("Der Strom ist teuer! Satz.", end_of_turn=True, speaker_label="A", turn_order=1)
        await session.stop()
        assert checker.check_claim_async.await_count == 1
        assert len(await db.get_fact_checks(session_id="s1")) == 1


class TestTranscriptFixes:
    async def test_turn_with_two_speakers_is_split_into_segments(self, db):
        events = []

        async def on_event(e):
            events.append(e)

        session = StreamingSession("s1", _gate([]), _fast_checker(), db, on_event=on_event,
                                   speaker_identifier=_ident())
        # Moderator question (0–2 s) glued to the guest's answer (2–8 s) in one turn.
        words = [{"text": w, "start": i * 500, "end": i * 500 + 450}
                 for i, w in enumerate("ist das falsch frau dröge nein das ist richtig so "
                                       "und zwar schon lange".split())]
        session._spk_track.add(0, 2000, "Maischberger", 0.8)
        for t in range(2000, 7000, 1000):
            session._spk_track.add(t, t + 3000, "Dröge", 0.8)
        await session.handle_turn("Ist das falsch, Frau Dröge? Nein, das ist richtig so und zwar schon lange.",
                                  end_of_turn=True, speaker_label="C", turn_order=0, words=words)
        upd = next(e for e in events if e["type"] == "turn_speaker_update")
        assert upd["speaker"] == "Dröge"
        assert upd["segments"] == [
            {"speaker": "Maischberger", "text": "Ist das falsch, Frau Dröge?"},
            {"speaker": "Dröge", "text": "Nein, das ist richtig so und zwar schon lange."},
        ]
        await session.stop()

    async def test_single_speaker_turn_has_no_segments(self, db):
        events = []

        async def on_event(e):
            events.append(e)

        session = StreamingSession("s1", _gate([]), _fast_checker(), db, on_event=on_event,
                                   speaker_identifier=_ident())
        await _voted_turn(session, 0, "A", "Connemann")
        upd = next(e for e in events if e["type"] == "turn_speaker_update")
        assert upd == {"type": "turn_speaker_update", "turn_order": 0, "speaker": "Connemann"}
        await session.stop()

    async def test_early_claim_source_resent_in_final_wording(self, db):
        events = []

        async def on_event(e):
            events.append(e)

        claim = GatedClaim(name="", claim="Die Industrie hat die Strompreise hochgebracht.",
                           source="hat die Industrie Strompreise hochgebracht.")
        session = StreamingSession("s1", _gate([[claim]]), _fast_checker(), db, on_event=on_event)
        await session.handle_turn("hat die Industrie Strompreise hochgebracht. Und viertens, der Ausbau. Und",
                                  end_of_turn=False, turn_order=5)
        await _drain(session)
        await session.handle_turn("Hat die Industrie Strompreise hochgebracht. Und viertens, der Ausbau.",
                                  end_of_turn=True, turn_order=5)
        assert {"type": "claim_source_update", "old": "hat die Industrie Strompreise hochgebracht.",
                "source": "Hat die Industrie Strompreise hochgebracht."} in events
        await session.stop()
