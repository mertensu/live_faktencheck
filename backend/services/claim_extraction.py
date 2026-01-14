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

logger = logging.getLogger(__name__)

# Default model if not specified in environment
DEFAULT_MODEL = "gemini-2.5-flash"


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

    def extract(self, transcript: str, guests: str) -> List[Dict[str, str]]:
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

        # Build prompt from template (use replace to avoid issues with JSON braces)
        prompt = self.prompt_template.replace("{guests}", guests).replace("{transcript}", transcript)

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            claims = self._parse_response(response.text)

            logger.info(f"Extracted {len(claims)} claims")
            return claims

        except Exception as e:
            logger.error(f"Claim extraction failed: {e}")
            raise

    def _parse_response(self, response_text: str) -> List[Dict[str, str]]:
        """
        Parse the Gemini response and extract claims JSON.

        Args:
            response_text: Raw text response from Gemini

        Returns:
            List of claim dictionaries
        """
        # Clean up response - remove markdown code blocks if present
        cleaned = response_text.strip()
        cleaned = re.sub(r"```json\s*", "", cleaned)
        cleaned = re.sub(r"```\s*$", "", cleaned)
        cleaned = cleaned.strip()

        try:
            claims = json.loads(cleaned)

            # Validate structure
            if not isinstance(claims, list):
                logger.warning("Response is not a list, wrapping in list")
                claims = [claims] if claims else []

            # Ensure each claim has required fields
            validated_claims = []
            for claim in claims:
                if isinstance(claim, dict) and "name" in claim and "claim" in claim:
                    validated_claims.append({
                        "name": str(claim["name"]),
                        "claim": str(claim["claim"])
                    })
                else:
                    logger.warning(f"Skipping invalid claim structure: {claim}")

            return validated_claims

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.error(f"Response was: {cleaned[:500]}...")
            return []
