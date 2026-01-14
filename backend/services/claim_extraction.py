"""
Claim Extraction Service using Google Gemini

Extracts verifiable factual claims from German transcripts.
"""

import os
import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any

from google import genai
from pydantic import BaseModel, Field

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

        # Load prompt template
        self.prompt_template = self._load_prompt_template()

        logger.info(f"ClaimExtractor initialized with model: {self.model_name}")

    def _load_prompt_template(self) -> str:
        """Load the claim extraction prompt template from file."""
        # Try multiple possible locations
        possible_paths = [
            Path(__file__).parent.parent.parent / "prompts" / "claim_extraction.md",
            Path("prompts/claim_extraction.md"),
            Path("/Users/ulfmertens/Documents/fact_check/prompts/claim_extraction.md"),
        ]

        for prompt_path in possible_paths:
            if prompt_path.exists():
                logger.info(f"Loading prompt from: {prompt_path}")
                return prompt_path.read_text(encoding="utf-8")

        raise FileNotFoundError(
            f"Could not find claim_extraction.md prompt file. Tried: {possible_paths}"
        )

    def extract(self, transcript: str, guests: str) -> List[ExtractedClaim]:
        """
        Extract verifiable claims from a transcript.

        Args:
            transcript: Formatted transcript with speaker labels
            guests: Context information about the show/guests

        Returns:
            List of claim dictionaries with 'name' and 'claim' keys

        Raises:
            Exception: If extraction fails
        """
        logger.info(f"Extracting claims from transcript ({len(transcript)} chars)")
        
        prompt = self.prompt_template.replace("{guests}", guests).replace("{transcript}", transcript)

        try:
            # Native Structured Output Call
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config={
                    'response_mime_type': 'application/json',
                    'response_schema': ClaimList, # Forces the model to adhere
                }
            )
            
            # The SDK automatically parses the JSON into your Pydantic model
            # No more Regex needed!
            return response.parsed.claims

        except Exception as e:
            logger.error(f"Structured extraction failed: {e}")
            raise
