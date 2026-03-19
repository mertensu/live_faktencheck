"""
Claim Extraction Service using Google Gemini

Extracts verifiable factual claims from German transcripts.
"""

import os
import json
import asyncio
import logging
from typing import List
from datetime import datetime

from google import genai
from pydantic import BaseModel, Field

from backend.utils import load_prompt, load_lang_config

logger = logging.getLogger(__name__)

# Default model if not specified in environment
DEFAULT_MODEL = "gemini-2.5-flash"

_lang = load_lang_config()

class ExtractedClaim(BaseModel):
    """A standalone, decontextualized factual claim."""
    name: str = Field(description=_lang["schema"]["extracted_claim"]["name_description"])
    claim: str = Field(description=_lang["schema"]["extracted_claim"]["claim_description"])

class ClaimList(BaseModel):
    """List of extracted factual claims."""
    claims: List[ExtractedClaim]

class SpeakerLabelMapping(BaseModel):
    """Mapping from a generic speaker label to a real name."""
    label: str = Field(description='Generische Sprecherbezeichnung, z. B. "Sprecher A"')
    name: str = Field(description='Echter Name der Person, z. B. "Julia Berger"')

class ResolvedTranscript(BaseModel):
    """Speaker label mappings extracted from a transcript."""
    mappings: List[SpeakerLabelMapping]

class SpeakerLabelsInput(BaseModel):
    """Input for speaker label resolution."""
    context: str = Field(description="Teilnehmer und Datum der Sendung")
    transcript: str = Field(description="Transkript mit generischen Sprecherbezeichnungen")

class ClaimExtractionInput(BaseModel):
    """Input for claim extraction from a transcript."""
    context: str = Field(description="Teilnehmer und Datum der Sendung")
    transcript: str = Field(description="Transkript zur Analyse")
    previous_block_ending: str | None = Field(default=None, description="Letzte Zeilen des vorherigen Transkriptblocks zur Gewährleistung der Kontinuität")
    show_background: str | None = Field(default=None, description="Hintergrundinformationen zur Sendung (z.B. Gesetzentwürfe, Berichte)")


class ClaimExtractor:
    """Service for extracting verifiable claims from transcripts using Gemini."""

    _first_extraction_logged = False

    def __init__(self):
        # New SDK supports both GEMINI_API_KEY and GOOGLE_API_KEY
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set")

        self.client = genai.Client(api_key=api_key)

        # Get model from environment (allows easy experimentation)
        self.model_name = os.getenv("GEMINI_MODEL_CLAIM_EXTRACTION", DEFAULT_MODEL)

        # Load prompt templates and bake in input schemas
        prompt = load_prompt("claim_extraction.md")
        input_schema = json.dumps(ClaimExtractionInput.model_json_schema(), indent=2, ensure_ascii=False)
        self.prompt_template = prompt.replace("{input_schema}", input_schema)

        self.article_prompt_template = load_prompt("claim_extraction_article.md")
        self.selection_prompt_template = load_prompt("claim_selection.md")
        try:
            speaker_labels_prompt = load_prompt("speaker_labels.md")
            sl_schema = json.dumps(SpeakerLabelsInput.model_json_schema(), indent=2, ensure_ascii=False)
            self.speaker_labels_prompt_template = speaker_labels_prompt.replace("{input_schema}", sl_schema)
        except FileNotFoundError:
            self.speaker_labels_prompt_template = None

        logger.info(f"ClaimExtractor initialized with model: {self.model_name}")

    async def _resolve_speaker_labels_async(self, transcript: str, info: str) -> str:
        """Step 1: Identify speaker label→name mappings and apply them to the transcript."""
        user_message = SpeakerLabelsInput(context=info, transcript=transcript).model_dump_json(indent=2)
        response = await self.client.aio.models.generate_content(
            model=self.model_name,
            contents=user_message,
            config={
                'system_instruction': self.speaker_labels_prompt_template,
                'response_mime_type': 'application/json',
                'response_schema': ResolvedTranscript,
            },
        )
        for m in response.parsed.mappings:
            transcript = transcript.replace(m.label, m.name)
        return transcript

    async def extract_async(self, transcript: str, info: str, previous_context: str | None = None, show_background: str | None = None) -> List[ExtractedClaim]:
        """
        Extract verifiable claims from a transcript (async).

        Args:
            transcript: Formatted transcript with speaker labels
            info: Context information about the show/guests
            previous_context: Last few lines from the previous block's transcript, for continuity
            show_background: Pre-fetched background material for the episode (e.g. legislative drafts, reports)

        Returns:
            List of ExtractedClaim objects
        """
        logger.info(f"Extracting claims from transcript ({len(transcript)} chars)")

        if self.speaker_labels_prompt_template:
            transcript = await self._resolve_speaker_labels_async(transcript, info)
            logger.info(f"Speaker labels resolved ({len(transcript)} chars)")

        system_prompt = self.prompt_template

        user_message = ClaimExtractionInput(
            context=info,
            transcript=transcript,
            previous_block_ending=previous_context,
            show_background=show_background,
        ).model_dump_json(indent=2)

        return await self._extract_async(system_prompt, user_message)

    def extract(self, transcript: str, info: str, previous_context: str | None = None, show_background: str | None = None) -> List[ExtractedClaim]:
        """
        Extract verifiable claims from a transcript (sync wrapper).

        Args:
            transcript: Formatted transcript with speaker labels
            info: Context information about the show/guests
            previous_context: Last few lines from the previous block's transcript, for continuity
            show_background: Pre-fetched background material for the episode

        Returns:
            List of ExtractedClaim objects

        Note:
            Use extract_async() in async contexts to avoid event loop conflicts.
        """
        return asyncio.run(self.extract_async(transcript, info, previous_context=previous_context, show_background=show_background))

    async def _extract_async(self, system_prompt: str, user_message: str) -> List[ExtractedClaim]:
        """Async implementation of claim extraction."""
        # Log first extraction to a file for prompt inspection
        if not ClaimExtractor._first_extraction_logged:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                log_path = os.path.join("logs", "prompt_dumps", f"{timestamp}_claim_extraction.txt")
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("=== SYSTEM PROMPT ===\n")
                    f.write(system_prompt)
                    f.write("\n\n=== USER MESSAGE ===\n")
                    f.write(user_message)
                ClaimExtractor._first_extraction_logged = True
                logger.info(f"First claim extraction prompt dumped to {log_path}")
            except Exception:
                logger.exception("Failed to dump first claim extraction prompt")

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=user_message,
                config={
                    'system_instruction': system_prompt,
                    'response_mime_type': 'application/json',
                    'response_schema': ClaimList,
                }
            )

            claims = response.parsed.claims
            logger.info(f"Extraction complete: {len(claims)} claims found")
            return claims

        except Exception:
            logger.exception("Structured extraction failed")
            raise

    async def extract_from_article_async(self, text: str, headline: str, publication_date: str = None) -> List[ExtractedClaim]:
        """
        Extract verifiable claims from an article (async).

        Args:
            text: Article text content
            headline: Article headline (used as context)
            publication_date: Publication date string (defaults to current month/year)

        Returns:
            List of ExtractedClaim objects
        """
        logger.info(f"Extracting claims from article ({len(text)} chars)")

        if not publication_date:
            publication_date = datetime.now().strftime("%B %Y")

        system_prompt = self.article_prompt_template.replace("{publication_date}", publication_date)

        user_message = f"""Headline: {headline}

Article: {text}"""

        return await self._extract_async(system_prompt, user_message)

    async def select_async(self, claims: List[dict], max_claims: int = 3) -> List[dict]:
        """
        Select the top N most fact-checkable claims from a list (autopilot mode).

        Args:
            claims: List of claim dicts with 'name' and 'claim' keys
            max_claims: Maximum number of claims to return

        Returns:
            Filtered list of claim dicts, at most max_claims entries
        """
        logger.info(f"Autopilot: selecting up to {max_claims} relevant claims from {len(claims)}...")

        claims_text = "\n".join(
            f"{i+1}. [{c.get('name', '?')}]: {c.get('claim', '')}"
            for i, c in enumerate(claims)
        )
        system_prompt = self.selection_prompt_template.replace("{max_claims}", str(max_claims))
        user_message = f"Behauptungen:\n{claims_text}"

        try:
            extracted = await self._extract_async(system_prompt, user_message)
            selected = [{"name": c.name, "claim": c.claim} for c in extracted]
            logger.info(f"Autopilot: selected {len(selected)} claims")
            return selected[:max_claims]
        except Exception:
            logger.exception("Claim selection failed, falling back to all claims (capped)")
            return claims[:max_claims]

    def extract_from_article(self, text: str, headline: str, publication_date: str = None) -> List[ExtractedClaim]:
        """
        Extract verifiable claims from an article (sync wrapper).

        Args:
            text: Article text content
            headline: Article headline (used as context)
            publication_date: Publication date string (defaults to current month/year)

        Returns:
            List of ExtractedClaim objects

        Note:
            Use extract_from_article_async() in async contexts to avoid event loop conflicts.
        """
        return asyncio.run(self.extract_from_article_async(text, headline, publication_date))
