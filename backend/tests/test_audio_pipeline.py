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
    mock_transcription.transcribe = MagicMock(return_value=raw_transcript)

    mock_extractor = MagicMock()
    mock_extractor.resolve_labels_async = AsyncMock(return_value=resolved_transcript)
    mock_extractor.extract_claims_async = AsyncMock(return_value=[])

    state.last_transcript_tail = None
    state.current_episode_key = "test-episode"
    state.pipeline_events["test-block"] = {"status": "processing"}

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_transcription), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_extractor), \
         patch("backend.routers.audio.EPISODES", {"test-episode": MagicMock(guests=[], date="", context="")}):
        await process_audio_pipeline_async("test-block", mock_audio_file, "test-episode")

    # Tail must contain resolved names, not generic labels
    assert state.last_transcript_tail is not None
    assert "Anna Müller" in state.last_transcript_tail
    assert "Sprecher A" not in state.last_transcript_tail


async def test_previous_block_ending_passed_with_resolved_names(mock_audio_file):
    """extract_claims_async receives the RESOLVED tail from the previous block as previous_context."""
    prev_resolved_tail = "Anna Müller: letzter Satz aus Block 1."
    raw_transcript = "Sprecher A: Neuer Block."
    resolved_transcript = "Karl Schmidt: Neuer Block."

    mock_transcription = MagicMock()
    mock_transcription.transcribe = MagicMock(return_value=raw_transcript)

    mock_extractor = MagicMock()
    mock_extractor.resolve_labels_async = AsyncMock(return_value=resolved_transcript)
    mock_extractor.extract_claims_async = AsyncMock(return_value=[])

    state.last_transcript_tail = prev_resolved_tail
    state.current_episode_key = "test-episode"
    state.pipeline_events["test-block-2"] = {"status": "processing"}

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_transcription), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_extractor), \
         patch("backend.routers.audio.EPISODES", {"test-episode": MagicMock(guests=[], date="", context="")}):
        await process_audio_pipeline_async("test-block-2", mock_audio_file, "test-episode")

    # extract_claims_async must receive the previous resolved tail
    call_kwargs = mock_extractor.extract_claims_async.call_args.kwargs
    assert call_kwargs["previous_context"] == prev_resolved_tail
