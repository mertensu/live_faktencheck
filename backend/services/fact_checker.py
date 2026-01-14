"""
Fact Checker Service using LangGraph with Gemini and Tavily Search

Verifies claims against authoritative German sources using a robust ReAct agent loop.
"""

import os
import json
import logging
import re
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_tavily import TavilySearch
from langgraph.prebuilt import create_react_agent

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
    """Service for fact-checking claims using LangGraph ReAct agent with Gemini and Tavily."""

    def __init__(self):
        # Get API keys
        google_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not google_api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set")

        tavily_api_key = os.getenv("TAVILY_API_KEY")
        if not tavily_api_key:
            raise ValueError("TAVILY_API_KEY environment variable not set")

        # Get model from environment
        self.model_name = os.getenv("GEMINI_MODEL_FACT_CHECKER", DEFAULT_MODEL)

        # Initialize LangChain components
        self.llm = ChatGoogleGenerativeAI(
            model=self.model_name,
            google_api_key=google_api_key,
            temperature=0,
            max_retries=2,
        )

        # Initialize Tavily search tool with domain restrictions
        self.search_tool = TavilySearch(
            max_results=5,
            search_depth="basic",
            include_domains=TRUSTED_DOMAINS,
        )

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

    def check_claim(self, speaker: str, claim: str) -> Dict[str, Any]:
        """
        Fact-check a single claim using LangGraph ReAct agent with Tavily search.

        Args:
            speaker: Name of the person who made the claim
            claim: The claim text to verify

        Returns:
            Dictionary with speaker, original_claim, verdict, evidence, sources
        """
        logger.info(f"Checking claim from {speaker}: {claim[:100]}...")

        current_date = datetime.now().strftime("%B %Y")

        # Build system prompt from template
        system_prompt = (
            self.prompt_template
            .replace("{current_date}", current_date)
            .replace("{speaker}", speaker)
            .replace("{claim}", claim)
        )

        try:
            # Create the ReAct agent graph
            agent = create_react_agent(
                model=self.llm,
                tools=[self.search_tool],
                prompt=system_prompt,
            )

            # Run the agent
            result = agent.invoke({
                "messages": [{"role": "user", "content": f"Überprüfe diese Behauptung: {claim}"}]
            })

            # Extract the final response from messages
            final_message = ""
            if result and "messages" in result:
                for msg in reversed(result["messages"]):
                    if hasattr(msg, "content") and msg.content:
                        final_message = msg.content
                        break

            # Parse the response
            parsed = self._parse_response(final_message, speaker, claim)
            logger.info(f"Claim checked: verdict = {parsed.get('verdict', 'unknown')}")
            return parsed

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
        results = [None] * len(claims)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_index = {
                executor.submit(
                    self.check_claim,
                    claim_data.get("name", "Unknown"),
                    claim_data.get("claim", "")
                ): i
                for i, claim_data in enumerate(claims)
            }

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
        Parse agent response into structured fact-check result.

        Args:
            response_text: Raw agent response
            speaker: Fallback speaker name
            claim: Fallback claim text

        Returns:
            Parsed fact-check dictionary
        """
        if not response_text:
            return {
                "speaker": speaker,
                "original_claim": claim,
                "verdict": "Unbelegt",
                "evidence": "Keine Antwort vom Modell erhalten.",
                "sources": []
            }

        # Try to extract JSON from the response
        cleaned = response_text.strip()

        # Remove markdown code blocks if present
        cleaned = re.sub(r"```json\s*", "", cleaned)
        cleaned = re.sub(r"```\s*$", "", cleaned)
        cleaned = cleaned.strip()

        # Try to find JSON object in the response
        json_match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', cleaned, re.DOTALL)
        if json_match:
            cleaned = json_match.group()

        try:
            result = json.loads(cleaned)

            return {
                "speaker": result.get("speaker", speaker),
                "original_claim": result.get("original_claim", claim),
                "verdict": result.get("verdict", "Unbelegt"),
                "evidence": result.get("evidence", ""),
                "sources": result.get("sources", [])
            }

        except json.JSONDecodeError as e:
            logger.warning(f"Could not parse JSON, extracting verdict from text: {e}")

            # Try to extract verdict from plain text
            verdict = "Unbelegt"
            for v in ["Richtig", "Falsch", "Teilweise Richtig"]:
                if v.lower() in response_text.lower():
                    verdict = v
                    break

            return {
                "speaker": speaker,
                "original_claim": claim,
                "verdict": verdict,
                "evidence": response_text,
                "sources": []
            }
