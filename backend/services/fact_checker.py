"""
Fact Checker Service using Google Gemini and Tavily Search

Verifies claims against authoritative German sources.
Uses Gemini's function calling to let the model search multiple times.
Supports both sequential and parallel processing.
"""

import os
import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from google import genai
from google.genai import types
from tavily import TavilyClient

logger = logging.getLogger(__name__)

# Default model if not specified in environment
DEFAULT_MODEL = "gemini-2.5-pro"

# Trusted domains for fact-checking searches
TRUSTED_DOMAINS = [
    # Government & Official Statistics
    "destatis.de",
    "bundesnetzagentur.de",
    "umweltbundesamt.de",
    "bmwk.de",
    "bundeshaushalt.de",
    "uba.de",
    "bundesbank.de",
    "publikationen-bundesregierung.de",  
    # Research Institutes
    "diw.de",
    "ifo.de",
    "iwkoeln.de",
    "zew.de",
    "iab.de",
    "fraunhofer.de",
    "pik-potsdam.de",
    "wupperinst.org",
    # Think Tanks & Foundations
    "boeckler.de",
    "swp-berlin.org",
    "agora-energiewende.de",
    "oeko.de",
    "steuerzahler.de",
    "portal-sozialpolitik.de",
    # Fact-Checking Organizations
    "correctiv.org",
    # EU Sources
    "ec.europa.eu",
    # Quality Journalism (for references only)
    "faz.net",
    "handelsblatt.com",
    "sueddeutsche.de",
]


class FactChecker:
    """Service for fact-checking claims using Gemini with Tavily as a tool."""

    def __init__(self):
        # Initialize Gemini - new SDK supports both env var names
        google_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not google_api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set")

        self.client = genai.Client(api_key=google_api_key)

        # Get model from environment (allows easy experimentation)
        self.model_name = os.getenv("GEMINI_MODEL_FACT_CHECKER", DEFAULT_MODEL)

        # Initialize Tavily
        tavily_api_key = os.getenv("TAVILY_API_KEY")
        if not tavily_api_key:
            raise ValueError("TAVILY_API_KEY environment variable not set")

        self.tavily = TavilyClient(api_key=tavily_api_key)

        # Load prompt template
        self.prompt_template = self._load_prompt_template()

        # Parallel processing settings
        self.parallel_enabled = os.getenv("FACT_CHECK_PARALLEL", "false").lower() == "true"
        self.max_workers = int(os.getenv("FACT_CHECK_MAX_WORKERS", "3"))

        logger.info(
            f"FactChecker initialized with model: {self.model_name}, "
            f"parallel: {self.parallel_enabled}, max_workers: {self.max_workers}"
        )

    def _load_prompt_template(self) -> str:
        """Load the fact checker prompt template from file."""
        possible_paths = [
            Path(__file__).parent.parent.parent / "prompts" / "fact_checker.md",
            Path("prompts/fact_checker.md"),
            Path("/Users/ulfmertens/Documents/fact_check/prompts/fact_checker.md"),
        ]

        for prompt_path in possible_paths:
            if prompt_path.exists():
                logger.info(f"Loading prompt from: {prompt_path}")
                return prompt_path.read_text(encoding="utf-8")

        raise FileNotFoundError(
            f"Could not find fact_checker.md prompt file. Tried: {possible_paths}"
        )

    def search_web(self, query: str) -> str:
        """
        Search the web for information using Tavily.

        This function is used as a tool by the Gemini model.
        The model can call this multiple times with different queries.

        Args:
            query: The search query in German. Should be specific and factual.

        Returns:
            A JSON string containing search results with titles, URLs, and content snippets.
        """
        logger.info(f"Tavily search: {query}")

        try:
            results = self.tavily.search(
                query=query,
                search_depth="basic",
                include_domains=TRUSTED_DOMAINS,
                max_results=5
            )

            # Format results for the model
            formatted_results = []
            for result in results.get("results", []):
                formatted_results.append({
                    "title": result.get("title", ""),
                    "url": result.get("url", ""),
                    "content": result.get("content", "")[:500]  # Truncate long content
                })

            logger.info(f"Found {len(formatted_results)} results")
            return json.dumps(formatted_results, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.warning(f"Tavily search failed: {e}")
            return json.dumps({"error": str(e)})

    def check_claim(self, speaker: str, claim: str) -> Dict[str, Any]:
        """
        Fact-check a single claim using Gemini with Tavily as a tool.

        The model can call the search tool multiple times to gather evidence.

        Args:
            speaker: Name of the person who made the claim
            claim: The claim text to verify

        Returns:
            Dictionary with speaker, original_claim, verdict, evidence, sources
        """
        logger.info(f"Checking claim from {speaker}: {claim[:100]}...")

        current_date = datetime.now().strftime("%B %Y")

        # Build system prompt from template (use replace to avoid issues with JSON braces)
        system_prompt = (
            self.prompt_template
            .replace("{current_date}", current_date)
            .replace("{speaker}", speaker)
            .replace("{claim}", claim)
        )

        user_prompt = f"This is the claim to check: {claim}"

        try:
            # Configure the model with the search tool
            config = types.GenerateContentConfig(
                tools=[self.search_web],
                system_instruction=system_prompt,
            )

            # Let Gemini handle the agentic loop (automatic function calling)
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user_prompt,
                config=config,
            )

            result = self._parse_response(response.text, speaker, claim)
            logger.info(f"Claim checked: verdict = {result.get('verdict', 'unknown')}")
            return result

        except Exception as e:
            logger.error(f"Fact-check failed for claim: {e}")
            return {
                "speaker": speaker,
                "original_claim": claim,
                "verdict": "Unbelegt",
                "evidence": f"Fehler bei der Überprüfung: {str(e)}",
                "sources": []
            }

    def check_claims(self, claims: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """
        Fact-check multiple claims (sequential or parallel based on config).

        Args:
            claims: List of claim dictionaries with 'name' and 'claim' keys

        Returns:
            List of fact-check result dictionaries
        """
        if not claims:
            return []

        logger.info(
            f"Checking {len(claims)} claims "
            f"({'parallel' if self.parallel_enabled else 'sequential'})"
        )

        if self.parallel_enabled:
            return self._check_claims_parallel(claims)
        else:
            return self._check_claims_sequential(claims)

    def _check_claims_sequential(self, claims: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Process claims one by one."""
        results = []
        for i, claim_data in enumerate(claims):
            logger.info(f"Processing claim {i + 1}/{len(claims)}")
            result = self.check_claim(
                speaker=claim_data.get("name", "Unknown"),
                claim=claim_data.get("claim", "")
            )
            results.append(result)
        return results

    def _check_claims_parallel(self, claims: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Process claims concurrently using ThreadPoolExecutor."""
        results = [None] * len(claims)  # Preserve order

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_index = {
                executor.submit(
                    self.check_claim,
                    claim_data.get("name", "Unknown"),
                    claim_data.get("claim", "")
                ): i
                for i, claim_data in enumerate(claims)
            }

            # Collect results as they complete
            for future in as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    results[index] = future.result()
                    logger.info(f"Completed claim {index + 1}/{len(claims)}")
                except Exception as e:
                    logger.error(f"Claim {index + 1} failed: {e}")
                    results[index] = {
                        "speaker": claims[index].get("name", "Unknown"),
                        "original_claim": claims[index].get("claim", ""),
                        "verdict": "Unbelegt",
                        "evidence": f"Fehler: {str(e)}",
                        "sources": []
                    }

        return results

    def _parse_response(
        self,
        response_text: str,
        speaker: str,
        claim: str
    ) -> Dict[str, Any]:
        """
        Parse Gemini response into structured fact-check result.

        Args:
            response_text: Raw Gemini response
            speaker: Fallback speaker name
            claim: Fallback claim text

        Returns:
            Parsed fact-check dictionary
        """
        # Clean up response - remove markdown code blocks
        cleaned = response_text.strip()
        cleaned = re.sub(r"```json\s*", "", cleaned)
        cleaned = re.sub(r"```\s*$", "", cleaned)
        cleaned = cleaned.strip()

        try:
            result = json.loads(cleaned)

            # Validate and ensure required fields
            return {
                "speaker": result.get("speaker", speaker),
                "original_claim": result.get("original_claim", claim),
                "verdict": result.get("verdict", "Unbelegt"),
                "evidence": result.get("evidence", ""),
                "sources": result.get("sources", [])
            }

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse verdict JSON: {e}")
            logger.error(f"Response was: {cleaned[:500]}...")

            return {
                "speaker": speaker,
                "original_claim": claim,
                "verdict": "Unbelegt",
                "evidence": "Fehler beim Parsen der KI-Antwort.",
                "sources": []
            }
