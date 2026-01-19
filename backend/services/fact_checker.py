"""
Fact Checker Service using LangGraph with Gemini and Tavily Search

Verifies claims against authoritative German sources using a robust ReAct agent loop.
"""

import os
import asyncio
import logging
from pathlib import Path
from typing import List, Dict, Any, Literal
from datetime import datetime

from pydantic import BaseModel, Field

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_tavily import TavilySearch
from langchain.agents import create_agent

logger = logging.getLogger(__name__)

# Default model if not specified in environment
DEFAULT_MODEL = "gemini-2.5-pro"

# Trusted domains for fact-checking searches
TRUSTED_DOMAINS = [
    # Government & Official Statistics
    "destatis.de",
    "bundesnetzagentur.de",
    "umweltbundesamt.de",
    "bundesfinanzministerium.de",
    "bundesumweltministerium.de",
    "bundesgesundheitsministerium.de",
    "auswaertiges-amt.de",
    "bmvg.de", 
    "bmas.de",
    "bundeswirtschaftsministerium.de",
    "bundeshaushalt.de",
    "umweltbundesamt.de",
    "bundesbank.de",
    "bundestag.de",
    "publikationen-bundesregierung.de",
    "bmds.bund.de",
    "gesetze-im-internet.de",
    # Research Institutes
    "diw.de",
    "ifo.de",
    "iwkoeln.de",
    "zew.de",
    "iab.de",
    "fraunhofer.de",
    "pik-potsdam.de",
    "wupperinst.org",
    "ewi.uni-koeln.de",
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
    "zeit.de"
]

# 1. Define the Data Structure
class FactCheckResponse(BaseModel):
    speaker: str
    original_claim: str
    verdict: Literal["Richtig", "Falsch", "Teilweise Richtig", "Unbelegt"]
    evidence: str = Field(description="Detailed German explanation")
    sources: List[str] = Field(description="URLs to primary sources")

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
        self.search_depth = os.getenv("TAVILY_SEARCH_DEPTH", "basic")
        self.max_results = int(os.getenv("TAVILY_MAX_RESULTS", "5"))
        self.search_tool = TavilySearch(
            name="fact_checker_search",
            description="Search the web to verify claims.",
            max_results=self.max_results,
            search_depth=self.search_depth,
            include_domains=TRUSTED_DOMAINS,
        )

        # Load prompt template
        self.prompt_template = self._load_prompt_template()

        # Parallel processing settings
        self.parallel_enabled = os.getenv("FACT_CHECK_PARALLEL", "false").lower() == "true"
        self.max_workers = int(os.getenv("FACT_CHECK_MAX_WORKERS", "3"))

        logger.info(
            f"FactChecker initialized with model: {self.model_name}, "
            f"search_depth: {self.search_depth}, max_results: {self.max_results}, "
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

        system_prompt = (
            self.prompt_template
            .replace("{current_date}", current_date)
            .replace("{speaker}", speaker)
            .replace("{claim}", claim)
        )

        # Use async to avoid sync client hanging issues
        return asyncio.run(self._check_claim_async(speaker, claim, system_prompt))

    async def _check_claim_async(self, speaker: str, claim: str, system_prompt: str) -> Dict[str, Any]:
        """Async implementation of claim checking."""
        try:
            agent = create_agent(
                model=self.llm,
                tools=[self.search_tool],
                system_prompt=system_prompt,
                response_format=FactCheckResponse,
            )

            result = await agent.ainvoke({
                "messages": [{"role": "user", "content": f"Check this claim: {claim}"}]
            })

            # Handle nested structured_response
            if "structured_response" in result:
                structured = result["structured_response"]
                parsed = structured.model_dump() if hasattr(structured, "model_dump") else structured
            else:
                # Result might already be flat
                parsed = result.model_dump() if hasattr(result, "model_dump") else result

            logger.info(f"Claim checked: verdict = {parsed.get('verdict', 'unknown')}")
            return parsed

        except Exception as e:
            logger.error(f"Fact-check failed for claim: {e}")
            import traceback
            traceback.print_exc()
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
        """
        Process claims concurrently using asyncio.gather with a semaphore.

        This avoids the nested event loop issue caused by RunnableLambda.batch()
        calling asyncio.run() inside an already-running loop.
        """
        return asyncio.run(self._check_claims_parallel_async(claims))

    async def _check_claims_parallel_async(self, claims: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Async implementation of parallel claim checking."""
        semaphore = asyncio.Semaphore(self.max_workers)

        async def check_with_limit(claim_data: Dict[str, str], index: int) -> Dict[str, Any]:
            """Check a single claim with concurrency limiting."""
            async with semaphore:
                speaker = claim_data.get("name", "Unknown")
                claim = claim_data.get("claim", "")
                logger.info(f"Processing claim {index + 1}/{len(claims)}: {claim[:50]}...")

                current_date = datetime.now().strftime("%B %Y")
                system_prompt = (
                    self.prompt_template
                    .replace("{current_date}", current_date)
                    .replace("{speaker}", speaker)
                    .replace("{claim}", claim)
                )

                result = await self._check_claim_async(speaker, claim, system_prompt)
                logger.info(f"Completed claim {index + 1}/{len(claims)}: {result.get('verdict', 'unknown')}")
                return result

        logger.info(f"Running {len(claims)} claims in parallel (max_concurrency: {self.max_workers})")

        # Run all claims concurrently (semaphore limits actual parallelism)
        results = await asyncio.gather(
            *[check_with_limit(claim, i) for i, claim in enumerate(claims)],
            return_exceptions=False
        )

        return list(results)

