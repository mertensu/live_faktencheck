"""
Transcription Service using AssemblyAI

Handles audio transcription with speaker detection for German language.
"""

import os
import logging

import assemblyai as aai

logger = logging.getLogger(__name__)

# Universal-3 Pro (with universal-2 as automatic fallback) is a promptable speech
# model: it accepts keyterms to boost domain-specific proper nouns. Overridable via
# env for easy rollback, e.g. ASSEMBLYAI_SPEECH_MODELS="universal-2".
DEFAULT_SPEECH_MODELS = "universal-3-pro,universal-2"


def keyterms_from_guests(guests: list[str]) -> list[str]:
    """Derive AssemblyAI keyterms from formatted guest strings.

    The wizard stores guests as "Name (Party/Org, Role)". For keyterms we want
    clean proper nouns: the name plus the first parenthetical segment (party/org).
    The second segment (role, e.g. "Moderatorin") is a common word and is dropped
    per AssemblyAI guidance to avoid redundant keyterms. Empties are skipped and
    duplicates removed (order preserved); capped at 1000 terms.
    """
    terms: list[str] = []
    for guest in guests:
        guest = (guest or "").strip()
        if not guest:
            continue
        name, _, rest = guest.partition("(")
        name = name.strip()
        if name:
            terms.append(name)
        if rest:
            first = rest.rstrip(")").split(",")[0].strip()
            if first:
                terms.append(first)

    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            deduped.append(term)
    return deduped[:1000]


class TranscriptionService:
    """Service for transcribing audio using AssemblyAI."""

    def __init__(self):
        api_key = os.getenv("ASSEMBLYAI_API_KEY")
        if not api_key:
            raise ValueError("ASSEMBLYAI_API_KEY environment variable not set")

        aai.settings.api_key = api_key
        self.speech_models = [
            m.strip()
            for m in os.getenv("ASSEMBLYAI_SPEECH_MODELS", DEFAULT_SPEECH_MODELS).split(",")
            if m.strip()
        ]

        logger.info(f"TranscriptionService initialized (speech_models={self.speech_models})")

    def _build_config(self, keyterms: list[str] | None) -> aai.TranscriptionConfig:
        """Build a per-call config. keyterms is added only when non-empty
        (an empty keyterms_prompt would needlessly trigger the paid add-on)."""
        kwargs = dict(
            speech_models=self.speech_models,
            language_code="de",
            speaker_labels=True,
        )
        if keyterms:
            kwargs["keyterms_prompt"] = keyterms
        return aai.TranscriptionConfig(**kwargs)

    def transcribe(self, audio_data: bytes, keyterms: list[str] | None = None) -> str:
        """
        Transcribe audio data and return formatted transcript with speaker labels.

        Args:
            audio_data: Raw audio bytes (WebM/Opus, MP4, or WAV — format auto-detected)
            keyterms: Optional proper nouns (names, parties/orgs) to boost recognition

        Returns:
            Formatted transcript string with speaker labels

        Raises:
            Exception: If transcription fails
        """
        logger.info(f"Starting transcription of {len(audio_data)} bytes ({len(keyterms or [])} keyterms)")

        # AssemblyAI SDK handles upload and polling automatically
        transcript = aai.Transcriber().transcribe(audio_data, self._build_config(keyterms))
        self._raise_on_error(transcript)

        formatted = self._format_transcript(transcript)
        logger.info(f"Transcription completed: {len(formatted)} characters")
        return formatted

    def transcribe_file(self, file_path: str, keyterms: list[str] | None = None) -> str:
        """
        Transcribe audio from a file path.

        Args:
            file_path: Path to audio file
            keyterms: Optional proper nouns to boost recognition

        Returns:
            Formatted transcript string with speaker labels
        """
        logger.info(f"Transcribing file: {file_path}")

        transcript = aai.Transcriber().transcribe(file_path, self._build_config(keyterms))
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
