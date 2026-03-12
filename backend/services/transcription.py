"""
Transcription Service using AssemblyAI

Handles audio transcription with speaker detection for German language.
"""

import os
import logging

import assemblyai as aai

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Service for transcribing audio using AssemblyAI."""

    def __init__(self):
        api_key = os.getenv("ASSEMBLYAI_API_KEY")
        if not api_key:
            raise ValueError("ASSEMBLYAI_API_KEY environment variable not set")

        aai.settings.api_key = api_key

        config = aai.TranscriptionConfig(
            language_code="de",
            speaker_labels=True,
        )
        self.transcriber = aai.Transcriber(config=config)

        logger.info("TranscriptionService initialized")

    def transcribe(self, audio_data: bytes) -> str:
        """
        Transcribe audio data and return formatted transcript with speaker labels.

        Args:
            audio_data: Raw audio bytes (WAV format)

        Returns:
            Formatted transcript string with speaker labels

        Raises:
            Exception: If transcription fails
        """
        logger.info(f"Starting transcription of {len(audio_data)} bytes")

        # AssemblyAI SDK handles upload and polling automatically
        transcript = self.transcriber.transcribe(audio_data)
        self._raise_on_error(transcript)

        formatted = self._format_transcript(transcript)
        logger.info(f"Transcription completed: {len(formatted)} characters")
        return formatted

    def transcribe_file(self, file_path: str) -> str:
        """
        Transcribe audio from a file path.

        Args:
            file_path: Path to audio file

        Returns:
            Formatted transcript string with speaker labels
        """
        logger.info(f"Transcribing file: {file_path}")

        transcript = self.transcriber.transcribe(file_path)
        self._raise_on_error(transcript)
        return self._format_transcript(transcript)

    def _raise_on_error(self, transcript: aai.Transcript) -> None:
        if transcript.status == aai.TranscriptStatus.error:
            error_msg = f"Transcription failed: {transcript.error}"
            logger.error(error_msg)
            raise Exception(error_msg)

    def _format_transcript(self, transcript: aai.Transcript) -> str:
        """
        Format transcript with speaker labels.

        Args:
            transcript: AssemblyAI transcript object

        Returns:
            Formatted string with "Sprecher X: text" format
        """
        if not transcript.utterances:
            # Fallback if no speaker detection
            logger.warning("No utterances found, returning raw text")
            return transcript.text or ""

        return "\n".join(
            f"Sprecher {u.speaker}: {u.text}" for u in transcript.utterances
        )
