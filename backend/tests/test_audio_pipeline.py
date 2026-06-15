"""Tests for the audio processing pipeline (state management)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import backend.state as state
from backend.routers.audio import process_audio_pipeline_async


@pytest.fixture
def mock_audio_file(tmp_path):
    """Create a temporary audio file for testing."""
    audio_file = tmp_path / "test.wav"
    audio_file.write_bytes(b"fake audio data")
    return str(audio_file)


async def test_last_transcript_tail_stored_with_resolved_names(mock_audio_file):
    """process_audio_pipeline_async stores RESOLVED transcript tail (real names, not generic labels)."""
    raw_transcript = "Sprecher A: Die Wirtschaft wächst.\nSprecher B: Das stimmt nicht."
    resolved_transcript = "Anna Müller: Die Wirtschaft wächst.\nKarl Schmidt: Das stimmt nicht."

    mock_transcription = MagicMock()
    mock_transcription.transcribe = MagicMock(return_value=(raw_transcript, 30.0))

    mock_extractor = MagicMock()
    mock_extractor.resolve_labels_async = AsyncMock(return_value=resolved_transcript)
    mock_extractor.extract_claims_async = AsyncMock(return_value=[])

    state.last_transcript_tails.clear()
    state.pipeline_events["test-block"] = {"status": "processing"}

    # Seed a session row so the DB lookup finds context
    await state.get_db().add_session({
        "session_id": "test-session",
        "title": "t",
        "guests": ["Anna Müller (Partei A)", "Karl Schmidt (Partei B)"],
        "date": "2026",
        "context": "ctx",
    })

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_transcription), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_extractor):
        await process_audio_pipeline_async("test-block", mock_audio_file, "test-session", None)

    # Tail must contain resolved names, not generic labels (stored under this session)
    stored_tail = state.last_transcript_tails["test-session"]
    assert stored_tail is not None
    assert "Anna Müller" in stored_tail
    assert "Sprecher A" not in stored_tail


async def test_transcript_tail_isolated_per_session(mock_audio_file):
    """Session B must NOT receive session A's transcript tail as previous_context.

    The tail is cross-block context; sharing it across sessions would bleed one
    user's transcript into another's claim extraction.
    """
    mock_transcription = MagicMock()
    mock_transcription.transcribe = MagicMock(return_value=("Sprecher A: Hallo.", 30.0))

    mock_extractor = MagicMock()
    mock_extractor.resolve_labels_async = AsyncMock(return_value="Karl Schmidt: Hallo.")
    mock_extractor.extract_claims_async = AsyncMock(return_value=[])

    state.last_transcript_tails.clear()
    # Session A already has a stored tail from a previous block.
    state.last_transcript_tails["session-A"] = "Anna Müller: Geheimer Satz aus Session A."
    state.pipeline_events["block-B"] = {"status": "processing"}

    await state.get_db().add_session({
        "session_id": "session-B", "title": "t",
        "guests": ["Karl Schmidt"], "context": "ctx",
    })

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_transcription), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_extractor):
        await process_audio_pipeline_async("block-B", mock_audio_file, "session-B", None)

    # Session B's extraction must not see session A's tail.
    previous_context = mock_extractor.extract_claims_async.call_args.kwargs["previous_context"]
    assert previous_context is None
    assert "Session A" not in (previous_context or "")


async def test_previous_block_ending_passed_with_resolved_names(mock_audio_file):
    """extract_claims_async receives the RESOLVED tail from the previous block as previous_context."""
    prev_resolved_tail = "Anna Müller: letzter Satz aus Block 1."
    raw_transcript = "Sprecher A: Neuer Block."
    resolved_transcript = "Karl Schmidt: Neuer Block."

    mock_transcription = MagicMock()
    mock_transcription.transcribe = MagicMock(return_value=(raw_transcript, 30.0))

    mock_extractor = MagicMock()
    mock_extractor.resolve_labels_async = AsyncMock(return_value=resolved_transcript)
    mock_extractor.extract_claims_async = AsyncMock(return_value=[])

    state.last_transcript_tails.clear()
    state.last_transcript_tails["test-session-2"] = prev_resolved_tail
    state.pipeline_events["test-block-2"] = {"status": "processing"}

    # Seed a session row so the DB lookup finds context
    await state.get_db().add_session({
        "session_id": "test-session-2",
        "title": "t",
        "guests": ["Anna Müller (Partei A)", "Karl Schmidt (Partei B)"],
        "date": "2026",
        "context": "ctx",
    })

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_transcription), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_extractor):
        await process_audio_pipeline_async("test-block-2", mock_audio_file, "test-session-2", None)

    # extract_claims_async must receive the previous resolved tail
    call_kwargs = mock_extractor.extract_claims_async.call_args.kwargs
    assert call_kwargs["previous_context"] == prev_resolved_tail


async def test_conversation_type_passed_to_extractor(mock_audio_file):
    """The session's conversation_type reaches resolve + extract."""
    mock_transcription = MagicMock()
    mock_transcription.transcribe = MagicMock(return_value=("Sprecher A: Test.", 30.0))

    mock_extractor = MagicMock()
    mock_extractor.resolve_labels_async = AsyncMock(return_value="Anna: Test.")
    mock_extractor.extract_claims_async = AsyncMock(return_value=[])

    state.last_transcript_tails.clear()
    state.pipeline_events["ct-block"] = {"status": "processing"}

    await state.get_db().add_session({
        "session_id": "ct-sess", "title": "t", "guests": ["Anna"],
        "context": "ctx", "conversation_type": "private",
    })

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_transcription), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_extractor):
        await process_audio_pipeline_async("ct-block", mock_audio_file, "ct-sess", None)

    assert mock_extractor.resolve_labels_async.call_args.kwargs.get("conversation_type") == "private"
    assert mock_extractor.extract_claims_async.call_args.kwargs.get("conversation_type") == "private"


async def test_excluded_speakers_passed_to_extractor(mock_audio_file):
    """The session's excluded_speakers reaches extract_claims_async."""
    mock_transcription = MagicMock()
    mock_transcription.transcribe = MagicMock(return_value=("Sprecher A: Test.", 30.0))

    mock_extractor = MagicMock()
    mock_extractor.resolve_labels_async = AsyncMock(return_value="Caren Miosga: Test.")
    mock_extractor.extract_claims_async = AsyncMock(return_value=[])

    state.last_transcript_tails.clear()
    state.pipeline_events["exc-block"] = {"status": "processing"}

    await state.get_db().add_session({
        "session_id": "exc-sess", "title": "t",
        "guests": ["Caren Miosga (Moderatorin)"],
        "excluded_speakers": ["Caren Miosga"],
    })

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_transcription), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_extractor):
        await process_audio_pipeline_async("exc-block", mock_audio_file, "exc-sess", None)

    assert mock_extractor.extract_claims_async.call_args.kwargs.get("excluded_speakers") == ["Caren Miosga"]


async def test_keyterms_derived_from_guests_passed_to_transcription(mock_audio_file):
    """The session's guests become keyterms boosted by the transcription model."""
    mock_transcription = MagicMock()
    mock_transcription.transcribe = MagicMock(return_value=("Sprecher A: Test.", 30.0))

    mock_extractor = MagicMock()
    mock_extractor.resolve_labels_async = AsyncMock(return_value="Heidi Reichinnek: Test.")
    mock_extractor.extract_claims_async = AsyncMock(return_value=[])

    state.last_transcript_tails.clear()
    state.pipeline_events["kt-block"] = {"status": "processing"}

    await state.get_db().add_session({
        "session_id": "kt-sess", "title": "t",
        "guests": ["Heidi Reichinnek (Linke, Fraktionsvorsitzende)", "Caren Miosga (Moderatorin)"],
        "context": "ctx",
    })

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_transcription), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_extractor):
        await process_audio_pipeline_async("kt-block", mock_audio_file, "kt-sess", None)

    # transcribe(audio_data, keyterms) — keyterms is the 2nd positional arg
    call = mock_transcription.transcribe.call_args
    keyterms = call.args[1] if len(call.args) > 1 else call.kwargs.get("keyterms")
    assert keyterms == ["Heidi Reichinnek", "Linke", "Caren Miosga", "Moderatorin"]


async def test_pipeline_increments_audio_seconds_for_code(mock_audio_file):
    """The transcribed audio_duration is added to the code's lifetime budget."""
    mock_transcription = MagicMock()
    mock_transcription.transcribe = MagicMock(return_value=("Sprecher A: Test.", 47.0))

    mock_extractor = MagicMock()
    mock_extractor.resolve_labels_async = AsyncMock(return_value="Anna: Test.")
    mock_extractor.extract_claims_async = AsyncMock(return_value=[])

    state.last_transcript_tails.clear()
    state.pipeline_events["inc-block"] = {"status": "processing"}
    await state.get_db().add_code("inc-code", "ann")
    await state.get_db().add_session({"session_id": "inc-sess", "title": "t", "guests": [], "context": ""})

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_transcription), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_extractor):
        await process_audio_pipeline_async("inc-block", mock_audio_file, "inc-sess", "inc-code")

    assert (await state.get_db().get_code("inc-code"))["audio_seconds_used"] == 47
