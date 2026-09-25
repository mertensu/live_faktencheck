"""
Tests for StreamingSession windowing + autopilot pipeline (SG-3).

The AssemblyAI wiring (start/feed/stop transport) is out of scope here; these tests
drive handle_turn() directly with synthetic turns and mocked gate + fast_checker,
against a real in-memory DB, and assert the placeholder-then-update row sequence.
"""

import asyncio
import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.database import Database
from backend.services.claim_extraction import ExtractedClaim
from backend.services import streaming as streaming_mod
from backend.services.gate import GatedClaim
from backend.routers.stream import _handle_control
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
    async def check(speaker, claim, context=None, episode_date=None, queries=None):
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

    async def test_gate_search_queries_reach_checker(self, db):
        claim = GatedClaim(name="Julia", claim="Deutschland hat 83 Mio. Einwohner.",
                           source="Deutschland hat 83 Millionen Einwohner.",
                           search_queries=["Einwohnerzahl Deutschland Destatis"])
        checker = _fast_checker()
        session = StreamingSession("s1", _gate([[claim]]), checker, db)
        await session.handle_turn("Deutschland hat 83 Millionen Einwohner. Das ist viel.",
                                  end_of_turn=True, speaker_label="Julia")
        await session.stop()
        assert checker.check_claim_async.await_args.kwargs["queries"] == ["Einwohnerzahl Deutschland Destatis"]

    async def test_empty_gate_writes_no_rows(self, db):
        gate = _gate([[]])
        session = StreamingSession("s1", gate, _fast_checker(), db)
        await session.handle_turn("Guten Abend. Schön hier zu sein.", end_of_turn=True, speaker_label="Mod")
        await session.stop()
        assert await db.get_fact_checks(session_id="s1") == []

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

    async def test_speaker_revision_uses_assigned_name(self, db):
        """When the new label is already assigned, a revision rewrites to that name."""
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


async def _drain(session):
    while session._tasks:
        await asyncio.gather(*list(session._tasks))


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



def _collect():
    events = []

    async def on_event(e):
        events.append(e)
    return events, on_event


CLAIM_A = GatedClaim(name="A", claim="Behauptung A.", source="Behauptung A.")


class TestSpeakerAssignment:
    async def test_assignment_rewrites_stored_claims_of_that_label(self, db):
        events, on_event = _collect()
        session = StreamingSession("s1", _gate([[CLAIM_A]]), _fast_checker(), db,
                                   on_event=on_event, speakers=["Dröge", "Connemann"])
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await _drain(session)
        pid = (await db.get_fact_checks(session_id="s1"))[0]["id"]

        await session.assign_speaker("A", "Dröge")
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Dröge"
        assert {"type": "speaker_map_update", "label": "A", "speaker": "Dröge"} in events
        assert {"type": "claim_speaker_update", "id": pid, "speaker": "Dröge", "label": "A"} in events
        await session.stop()

    async def test_other_labels_untouched(self, db):
        session = StreamingSession("s1", _gate([[CLAIM_A]]), _fast_checker(), db, speakers=["Dröge"])
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await _drain(session)
        await session.assign_speaker("B", "Dröge")
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "A"
        await session.stop()

    async def test_assignment_applies_to_later_claims(self, db):
        checker = _fast_checker()
        session = StreamingSession("s1", _gate([[CLAIM_A]]), checker, db, speakers=["Dröge"])
        await session.assign_speaker("A", "Dröge")
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await session.stop()
        assert checker.check_claim_async.await_args.kwargs["speaker"] == "Dröge"
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Dröge"

    async def test_reassign_and_clear(self, db):
        session = StreamingSession("s1", _gate([[CLAIM_A]]), _fast_checker(), db,
                                   speakers=["Dröge", "Connemann"])
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await _drain(session)
        await session.assign_speaker("A", "Dröge")
        await session.assign_speaker("A", "Connemann")  # operator corrects a wrong pick
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Connemann"
        await session.assign_speaker("A", None)
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "A"
        assert session._speaker_map == {}
        await session.stop()

    async def test_unknown_name_is_ignored(self, db):
        events, on_event = _collect()
        session = StreamingSession("s1", _gate([]), _fast_checker(), db, on_event=on_event,
                                   speakers=["Dröge"])
        await session.assign_speaker("A", "Irgendwer")
        assert session._speaker_map == {} and events == []
        await session.stop()

    async def test_assignment_during_check_survives_checker_echo(self, db):
        checker = _fast_checker()
        release = asyncio.Event()
        orig = checker.check_claim_async.side_effect

        async def slow_check(**kw):
            await release.wait()
            return await orig(**kw)

        checker.check_claim_async.side_effect = slow_check
        session = StreamingSession("s1", _gate([[CLAIM_A]]), checker, db, speakers=["Dröge"])
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await asyncio.sleep(0.01)  # placeholder stored, check pending
        await session.assign_speaker("A", "Dröge")
        release.set()
        await session.stop()
        row = (await db.get_fact_checks(session_id="s1"))[0]
        assert row["sprecher"] == "Dröge" and row["status"] == ""

    async def test_revision_moves_claim_to_assigned_label(self, db):
        events, on_event = _collect()
        session = StreamingSession("s1", _gate([[CLAIM_A]]), _fast_checker(), db,
                                   on_event=on_event, speakers=["Dröge", "Connemann"])
        await session.assign_speaker("A", "Dröge")
        await session.assign_speaker("B", "Connemann")
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await _drain(session)
        await session.handle_speaker_revision([{"turn_order": 0, "speaker_label": "B"}])
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Connemann"
        assert {"type": "turn_speaker_update", "turn_order": 0, "label": "B",
                "segments": [{"label": "B", "text": "Behauptung A. Noch ein Satz."}]} in events
        # The claim now follows B: clearing A no longer touches it.
        await session.assign_speaker("A", None)
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Connemann"
        await session.stop()

    async def test_gate_guessed_name_is_not_used(self, db):
        """A name the gate made up (not a label of the window) never becomes the speaker."""
        claim = GatedClaim(name="Dröge", claim="X.", source="Nicht im Fenster.")
        checker = _fast_checker()
        session = StreamingSession("s1", _gate([[claim]]), checker, db)
        # One window with two labels, so neither is the obvious speaker.
        await session.handle_turn("Satz eins.", end_of_turn=True, speaker_label="A", turn_order=0)
        await session.handle_turn("Satz zwei.", end_of_turn=True, speaker_label="B", turn_order=1)
        await session.stop()
        rows = await db.get_fact_checks(session_id="s1")
        assert rows[0]["sprecher"] == streaming_mod.UNCLEAR_SPEAKER

    async def test_extractor_gate_name_matching_a_label_is_that_label(self, db):
        """The extractor gate has no source; its name is the window line's label."""
        session = StreamingSession("s1", _gate([[ExtractedClaim(name="A", claim="Behauptung A.")]]),
                                   _fast_checker(), db, speakers=["Dröge"])
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await _drain(session)
        await session.assign_speaker("A", "Dröge")
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Dröge"
        await session.stop()


def _words(*pairs):
    """Word stubs from (text, speaker) pairs; a text with spaces is split into words."""
    from types import SimpleNamespace
    return [SimpleNamespace(text=w, speaker=spk) for text, spk in pairs for w in text.split()]


class TestWordSpeakers:
    """A turn ends at a pause, not at a change of speaker: split it by its words' speakers."""

    def test_sentence_takes_majority_speaker(self):
        text = "Ist das völlig falsch, Frau Dröge? Also erstens war das meiste richtig."
        words = _words(("Ist das völlig falsch, Frau Dröge?", "C"), ("Also", "PENDING"),
                       ("erstens war das meiste", "A"), ("richtig.", "C"))
        assert streaming_mod.sentence_speakers(text, words, "A") == [
            ("Ist das völlig falsch, Frau Dröge?", "C"),
            ("Also erstens war das meiste richtig.", "A"),
        ]

    def test_without_words_every_sentence_keeps_the_turn_label(self):
        assert streaming_mod.sentence_speakers("Eins. Zwei.", None, "B") == [("Eins.", "B"), ("Zwei.", "B")]
        assert streaming_mod.speaker_segments([("Eins.", "B"), ("Zwei.", "B"), ("Drei.", "A")]) == [
            ("B", "Eins. Zwei."), ("A", "Drei.")]

    async def test_mixed_turn_splits_window_and_transcript(self, db):
        events, on_event = _collect()
        gate, windows = _recording_gate()
        session = StreamingSession("s1", gate, _fast_checker(), db, on_event=on_event)
        text = "Ist das falsch, Frau Dröge? Also erstens war das meiste richtig."
        await session.handle_turn(text, end_of_turn=True, speaker_label="A", turn_order=0,
                                  words=_words(("Ist das falsch, Frau Dröge?", "C"),
                                               ("Also erstens war das meiste richtig.", "A")))
        assert windows == ["C: Ist das falsch, Frau Dröge?\nA: Also erstens war das meiste richtig."]
        turn = next(e for e in events if e["type"] == "turn")
        assert turn["segments"] == [{"label": "C", "text": "Ist das falsch, Frau Dröge?"},
                                    {"label": "A", "text": "Also erstens war das meiste richtig."}]
        await session.stop()

    async def test_claim_takes_its_sentences_speaker(self, db):
        claim = GatedClaim(name="A", claim="Strom ist teuer.", source="Der Strom ist teuer.")
        session = StreamingSession("s1", _gate([[claim]]), _fast_checker(), db, speakers=["Connemann"])
        await session.assign_speaker("B", "Connemann")
        await session.handle_turn("Was sagen Sie? Der Strom ist teuer.", end_of_turn=True, speaker_label="A",
                                  turn_order=0, words=_words(("Was sagen Sie?", "A"), ("Der Strom ist teuer.", "B")))
        await session.stop()
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Connemann"

    async def test_revision_resplits_turn_and_moves_claim_per_sentence(self, db):
        events, on_event = _collect()
        claim = GatedClaim(name="A", claim="Strom ist teuer.", source="Der Strom ist teuer.")
        session = StreamingSession("s1", _gate([[claim]]), _fast_checker(), db, on_event=on_event)
        await session.handle_turn("Was sagen Sie? Der Strom ist teuer.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await _drain(session)
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "A"
        await session.handle_speaker_revision([{
            "turn_order": 0, "speaker_label": "C",
            "words": _words(("Was sagen Sie?", "C"), ("Der Strom ist teuer.", "B")),
        }])
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "B"
        update = next(e for e in events if e["type"] == "turn_speaker_update")
        assert update["segments"] == [{"label": "C", "text": "Was sagen Sie?"},
                                      {"label": "B", "text": "Der Strom ist teuer."}]
        await session.stop()


class TestEarlySentenceSpeakers:
    """Partials carry no speakers, so an early sentence's claim gets its label from the final turn."""

    async def test_early_claim_labelled_when_turn_is_final(self, db):
        events, on_event = _collect()
        claim = GatedClaim(name="", claim="Strom ist teuer.", source="Der Strom ist teuer.")
        session = StreamingSession("s1", _gate([[claim]]), _fast_checker(), db, on_event=on_event,
                                   speakers=["Connemann"])
        await session.handle_turn("Der Strom ist teuer. Die Preise steigen. Und", end_of_turn=False, turn_order=0)
        await _drain(session)
        row = (await db.get_fact_checks(session_id="s1"))[0]
        assert row["sprecher"] == streaming_mod.UNCLEAR_SPEAKER

        await session.handle_turn("Der Strom ist teuer. Die Preise steigen. Und das seit Jahren.",
                                  end_of_turn=True, speaker_label="A", turn_order=0,
                                  words=_words(("Der Strom ist teuer.", "B"), ("Die Preise steigen.", "A"),
                                               ("Und das seit Jahren.", "A")))
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "B"
        assert {"type": "claim_speaker_update", "id": row["id"], "speaker": "B", "label": "B"} in events
        # From now on it follows its label like any other claim.
        await session.assign_speaker("B", "Connemann")
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Connemann"
        await session.stop()

    async def test_early_claim_stored_after_the_turn_is_final(self, db):
        """The gate was slower than the end of the turn: the label is there on insert."""
        claim = GatedClaim(name="", claim="Strom ist teuer.", source="Der Strom ist teuer.")
        release = asyncio.Event()

        async def slow_gate(window_text, guests, **kw):
            await release.wait()
            return [claim]

        gate = MagicMock()
        gate.gate = AsyncMock(side_effect=slow_gate)
        checker = _fast_checker()
        session = StreamingSession("s1", gate, checker, db)
        early = asyncio.create_task(session.handle_turn("Der Strom ist teuer. Die Preise steigen. Und",
                                                        end_of_turn=False, turn_order=0))
        await asyncio.sleep(0.01)
        final = asyncio.create_task(session.handle_turn(
            "Der Strom ist teuer. Die Preise steigen. Und das.", end_of_turn=True, speaker_label="A",
            turn_order=0, words=_words(("Der Strom ist teuer.", "B"), ("Die Preise steigen. Und das.", "A"))))
        await asyncio.sleep(0.01)
        release.set()
        await asyncio.gather(early, final)
        await session.stop()
        assert checker.check_claim_async.await_args_list[0].kwargs["speaker"] == "B"
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "B"

    async def test_unmatched_early_claim_stays_unclear(self, db):
        """No guessing: a claim whose sentence isn't in the final turn keeps "Unklar"."""
        claim = GatedClaim(name="", claim="X.", source="Ganz anderer Satz hier.")
        session = StreamingSession("s1", _gate([[claim]]), _fast_checker(), db)
        await session.handle_turn("Ganz anderer Satz hier. Zwei. Und", end_of_turn=False, turn_order=0)
        await _drain(session)
        await session.handle_turn("Etwas völlig Neues.", end_of_turn=True, speaker_label="A", turn_order=0)
        await session.stop()
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == streaming_mod.UNCLEAR_SPEAKER


class TestPassageAssignment:
    """The operator marks a passage that diarization put under the wrong label."""

    async def test_passage_rewrites_claim_and_detaches_it_from_its_label(self, db):
        events, on_event = _collect()
        session = StreamingSession("s1", _gate([[CLAIM_A]]), _fast_checker(), db,
                                   on_event=on_event, speakers=["Dröge", "Maischberger"])
        await session.assign_speaker("A", "Dröge")
        await session.handle_turn("Noch ein Satz. Behauptung A.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await _drain(session)
        pid = (await db.get_fact_checks(session_id="s1"))[0]["id"]

        await session.assign_passage("Behauptung A.", "Maischberger")
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Maischberger"
        assert {"type": "claim_speaker_update", "id": pid, "speaker": "Maischberger", "label": None} in events
        # Neither a new name for A nor a reclustering of its turn takes the claim back.
        await session.assign_speaker("A", None)
        await session.handle_speaker_revision([{"turn_order": 0, "speaker_label": "B"}])
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Maischberger"
        await session.stop()

    async def test_passage_leaves_claims_outside_it_alone(self, db):
        session = StreamingSession("s1", _gate([[CLAIM_A]]), _fast_checker(), db, speakers=["Maischberger"])
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await _drain(session)
        await session.assign_passage("Noch ein Satz.", "Maischberger")
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "A"
        await session.stop()

    async def test_passage_covering_most_of_a_sentence_counts(self, db):
        claim = GatedClaim(name="A", claim="X.", source="Die Inflation lag bei zehn Prozent im Jahr.")
        session = StreamingSession("s1", _gate([[claim]]), _fast_checker(), db, speakers=["Maischberger"])
        await session.handle_turn("Die Inflation lag bei zehn Prozent im Jahr. Gut.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await _drain(session)
        await session.assign_passage("Inflation lag bei zehn Prozent", "Maischberger")
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Maischberger"
        await session.assign_passage("zehn", "A")  # not a speaker: ignored
        await session.stop()

    async def test_passage_marked_before_the_claim_is_found(self, db):
        checker = _fast_checker()
        session = StreamingSession("s1", _gate([[CLAIM_A]]), checker, db, speakers=["Maischberger"])
        await session.assign_passage("Behauptung A.", "Maischberger")
        await session.handle_turn("Behauptung A. Noch ein Satz.", end_of_turn=True,
                                  speaker_label="A", turn_order=0)
        await session.stop()
        assert checker.check_claim_async.await_args.kwargs["speaker"] == "Maischberger"
        assert (await db.get_fact_checks(session_id="s1"))[0]["sprecher"] == "Maischberger"

    async def test_unknown_name_is_ignored(self, db):
        session = StreamingSession("s1", _gate([]), _fast_checker(), db, speakers=["Dröge"])
        await session.assign_passage("Behauptung A.", "Irgendwer")
        assert session._passages == []
        await session.stop()


class TestSpeakerRuns:
    def test_groups_consecutive_word_speakers(self):
        from types import SimpleNamespace as W
        words = [W(text="Was", speaker="A"), W(text="sagen", speaker="A"), W(text="Sie?", speaker="A"),
                 W(text="Das", speaker="B"), W(text="stimmt.", speaker="PENDING"), W(text="Ja.", speaker=None)]
        assert streaming_mod.speaker_runs(words) == [("A", "Was sagen Sie?"), ("B", "Das stimmt. Ja.")]
        assert streaming_mod.speaker_runs([W(text="Hm", speaker="PENDING"), W(text="ja", speaker="A")]) == [("A", "Hm ja")]
        assert streaming_mod.speaker_runs([]) == []


class TestControlMessages:
    async def test_assign_message_reaches_session(self, db):
        session = StreamingSession("s1", _gate([]), _fast_checker(), db, speakers=["Dröge"])
        await _handle_control(session, json.dumps({"type": "assign_speaker", "label": "A", "speaker": "Dröge"}))
        assert session._speaker_map == {"A": "Dröge"}
        await _handle_control(session, json.dumps({"type": "assign_speaker", "label": "A", "speaker": None}))
        assert session._speaker_map == {}
        await session.stop()

    async def test_passage_message_reaches_session(self, db):
        session = StreamingSession("s1", _gate([]), _fast_checker(), db, speakers=["Dröge"])
        await _handle_control(session, json.dumps({"type": "assign_passage", "text": "Ein Satz.", "speaker": "Dröge"}))
        await _handle_control(session, json.dumps({"type": "assign_passage", "text": "Ein Satz.", "speaker": None}))
        assert session._passages == [("ein satz", "Dröge")]
        await session.stop()

    async def test_garbage_is_ignored(self, db):
        session = StreamingSession("s1", _gate([]), _fast_checker(), db, speakers=["Dröge"])
        for text in ["kein json", "[1, 2]", json.dumps({"type": "other"}),
                     json.dumps({"type": "assign_speaker", "label": 5, "speaker": "Dröge"})]:
            await _handle_control(session, text)
        assert session._speaker_map == {}
        await session.stop()
