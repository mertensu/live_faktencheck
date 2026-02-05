"""
Claim Extraction Service using Google Gemini

Extracts verifiable factual claims from German transcripts.
"""

import os
import asyncio
import logging
from typing import List
from datetime import datetime

from google import genai
from pydantic import BaseModel, Field

from backend.utils import load_prompt

logger = logging.getLogger(__name__)

# Default model if not specified in environment
DEFAULT_MODEL = "gemini-2.5-flash"

class ExtractedClaim(BaseModel):
    """A standalone, decontextualized factual claim."""
    name: str = Field(description="Full name of the speaker (proper noun).")
    claim: str = Field(description="The German decontextualized claim (Atomic Claim).")

class ClaimList(BaseModel):
    """List of extracted factual claims."""
    claims: List[ExtractedClaim]


class ClaimExtractor:
    """Service for extracting verifiable claims from transcripts using Gemini."""

    def __init__(self):
        # New SDK supports both GEMINI_API_KEY and GOOGLE_API_KEY
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set")

        self.client = genai.Client(api_key=api_key)

        # Get model from environment (allows easy experimentation)
        self.model_name = os.getenv("GEMINI_MODEL_CLAIM_EXTRACTION", DEFAULT_MODEL)

        # Load prompt templates
        self.prompt_template = load_prompt("claim_extraction.md")
        self.article_prompt_template = load_prompt("claim_extraction_article.md")

        logger.info(f"ClaimExtractor initialized with model: {self.model_name}")

    async def extract_async(self, transcript: str, info: str, previous_context: str | None = None) -> List[ExtractedClaim]:
        """
        Extract verifiable claims from a transcript (async).

        Args:
            transcript: Formatted transcript with speaker labels
            info: Context information about the show/guests
            previous_context: Last few lines from the previous block's transcript, for continuity

        Returns:
            List of ExtractedClaim objects
        """
        logger.info(f"Extracting claims from transcript ({len(transcript)} chars)")

        system_prompt = self.prompt_template

        parts = []
        if previous_context:
            parts.append(f"""<previous_block_ending>
{previous_context}
</previous_block_ending>
""")
        parts.append(f"""<context>
Participants and date: {info}
</context>

<transcript>
{transcript}
</transcript>""")

        user_message = "\n".join(parts)

        return await self._extract_async(system_prompt, user_message)

    def extract(self, transcript: str, info: str, previous_context: str | None = None) -> List[ExtractedClaim]:
        """
        Extract verifiable claims from a transcript (sync wrapper).

        Args:
            transcript: Formatted transcript with speaker labels
            info: Context information about the show/guests
            previous_context: Last few lines from the previous block's transcript, for continuity

        Returns:
            List of ExtractedClaim objects

        Note:
            Use extract_async() in async contexts to avoid event loop conflicts.
        """
        return asyncio.run(self.extract_async(transcript, info, previous_context=previous_context))

    async def _extract_async(self, system_prompt: str, user_message: str) -> List[ExtractedClaim]:
        """Async implementation of claim extraction."""
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
