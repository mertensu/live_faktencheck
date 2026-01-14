"""
Transcription Service using AssemblyAI

Handles audio transcription with speaker detection for German language.
"""

import os
import logging
from typing import Optional

import assemblyai as aai

logger = logging.getLogger(__name__)


class TranscriptionService:
    """Service for transcribing audio using AssemblyAI."""

    def __init__(self):
        api_key = os.getenv("ASSEMBLYAI_API_KEY")
        if not api_key:
            raise ValueError("ASSEMBLYAI_API_KEY environment variable not set")

        aai.settings.api_key = api_key

        # Configure for German with speaker detection
        self.config = aai.TranscriptionConfig(
            language_detection=True,
            speaker_labels=True,
        )

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

        transcriber = aai.Transcriber(config=self.config)

        # AssemblyAI SDK handles upload and polling automatically
        transcript = transcriber.transcribe(audio_data)

        if transcript.status == aai.TranscriptStatus.error:
            error_msg = f"Transcription failed: {transcript.error}"
            logger.error(error_msg)
            raise Exception(error_msg)

        # Format transcript with speaker labels
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

        transcriber = aai.Transcriber(config=self.config)
        transcript = transcriber.transcribe(file_path)

        if transcript.status == aai.TranscriptStatus.error:
            error_msg = f"Transcription failed: {transcript.error}"
            logger.error(error_msg)
            raise Exception(error_msg)

        return self._format_transcript(transcript)

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

        lines = []
        for utterance in transcript.utterances:
            lines.append(f"Sprecher {utterance.speaker}: {utterance.text}")

        return "\n".join(lines)
