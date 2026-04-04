"""
Fact Checker Service using LangGraph with Gemini and Tavily Search

Verifies claims against authoritative German sources using a robust ReAct agent loop.
"""

import os
import json
import asyncio
import logging
from typing import List, Dict, Any, Literal, Optional
from datetime import datetime

from pydantic import BaseModel, Field, PrivateAttr
from google import genai

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.tools import BaseTool
from langchain_core.tools.base import ToolException
from langchain_core.callbacks import CallbackManagerForToolRun, AsyncCallbackManagerForToolRun
from langchain_tavily import TavilySearch
from langchain_tavily.tavily_search import TavilySearchInput
from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError

from backend.utils import load_prompt, to_dict
from backend.lang import (
    SOURCE_URL_DESCRIPTION,
    SOURCE_TITLE_DESCRIPTION,
    CONSISTENCY_DESCRIPTION,
    EVIDENCE_DESCRIPTION,
    SOURCES_DESCRIPTION,
    CRITIQUE_CONFIDENCE_DESCRIPTION,
    CRITIQUE_REASON_DESCRIPTION,
)
from .cost_tracker import get_cost_tracker
from .trusted_domains import TRUSTED_DOMAINS

logger = logging.getLogger(__name__)

# Default model if not specified in environment
DEFAULT_MODEL = "gemini-2.5-pro"


# 1. Define the Data Structure
class Source(BaseModel):
    url: str = Field(description=SOURCE_URL_DESCRIPTION)
    title: str = Field(description=SOURCE_TITLE_DESCRIPTION)

class FactCheckResponse(BaseModel):
    speaker: str
    original_claim: str
    consistency: Literal["hoch", "niedrig", "unklar", "keine Datenlage"] = Field(
        description=CONSISTENCY_DESCRIPTION
    )
    evidence: str = Field(description=EVIDENCE_DESCRIPTION)
    sources: List[Source] = Field(description=SOURCES_DESCRIPTION)

class SelfCritiqueInput(BaseModel):
    """Eingabe für die Selbstkritik eines Faktencheck-Urteils."""
    behauptung: str = Field(description="Die überprüfte Behauptung")
    urteil: Literal["hoch", "niedrig", "unklar", "keine Datenlage"] = Field(description=CONSISTENCY_DESCRIPTION)
    begruendung: str = Field(description="Die Begründung des Faktencheckers")

class SelfCritiqueResponse(BaseModel):
    confidence: Literal["high", "low"] = Field(description=CRITIQUE_CONFIDENCE_DESCRIPTION)
    reason: str = Field(default="", description=CRITIQUE_REASON_DESCRIPTION)


class ClaimInput(BaseModel):
    """Behauptung zur Faktenprüfung."""
    context: str = Field(description="Thematischer Hintergrund der Sendung")
    sprecher: str = Field(description="Name des Sprechers")
    sendedatum: str = Field(description="Monat und Jahr der Sendung, z.B. 'März 2026'")
    behauptung: str = Field(description="Die zu überprüfende Behauptung")


class FallbackSearchTool(BaseTool):
    """TavilySearch wrapper that retries without date filters when results are empty."""

    name: str = "fact_checker_search"
    description: str = "Search the web to verify claims."
    args_schema: type = TavilySearchInput
    handle_tool_error: bool = True

    _search: TavilySearch = PrivateAttr()

    def __init__(self, search: TavilySearch, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._search = search

    def _run(
        self,
        query: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        run_manager: Optional[CallbackManagerForToolRun] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        try:
            return self._search._run(
                query=query, start_date=start_date, end_date=end_date,
                run_manager=run_manager, **kwargs,
            )
        except ToolException:
            if start_date or end_date:
                logger.info("Empty results with date filter — retrying without date filter: '%s'", query)
                return self._search._run(query=query, run_manager=run_manager, **kwargs)
            raise

    async def _arun(
        self,
        query: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        run_manager: Optional[AsyncCallbackManagerForToolRun] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        try:
            return await self._search._arun(
                query=query, start_date=start_date, end_date=end_date,
                run_manager=run_manager, **kwargs,
            )
        except ToolException:
            if start_date or end_date:
                logger.info("Empty results with date filter — retrying without date filter: '%s'", query)
                return await self._search._arun(query=query, run_manager=run_manager, **kwargs)
            raise


class FactChecker:
    """Service for fact-checking claims using LangGraph ReAct agent with Gemini and Tavily."""

    _first_claim_logged = False

    def __init__(self):
        # Get API keys
        google_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not google_api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set")

        # Get model from environment
        self.model_name = os.getenv("GEMINI_MODEL_FACT_CHECKER", DEFAULT_MODEL)
        self.fallback_model_name = os.getenv("GEMINI_MODEL_FACT_CHECKER_FALLBACK", "gemini-3-flash-preview")

        # Initialize LangChain components with fallback model for 503/overload errors
        primary_llm = ChatGoogleGenerativeAI(
            model=self.model_name,
            google_api_key=google_api_key,
            temperature=0,
            max_retries=1,
        )
        fallback_llm = ChatGoogleGenerativeAI(
            model=self.fallback_model_name,
            google_api_key=google_api_key,
            temperature=0,
            max_retries=1,
        )
        self.llm = primary_llm.with_fallbacks([fallback_llm])

        # Initialize search tool (Mock or Tavily)
        # Mock search is ONLY enabled when MOCK_SEARCH=true AND running in test environment
        self.use_mock_search = (
            os.getenv("MOCK_SEARCH", "false").lower() == "true"
            and os.getenv("PYTEST_CURRENT_TEST") is not None
        )
        self.search_depth = os.getenv("TAVILY_SEARCH_DEPTH", "basic")
        self.max_results = int(os.getenv("TAVILY_MAX_RESULTS", "5"))

        if self.use_mock_search:
            logger.info("Initializing with MOCK SEARCH tool (test environment only)")
            from .mock_search import mock_search
            self.search_tool = mock_search
        else:
            tavily_api_key = os.getenv("TAVILY_API_KEY")
            if not tavily_api_key:
                raise ValueError("TAVILY_API_KEY environment variable not set (and MOCK_SEARCH is false)")

            self.search_tool = FallbackSearchTool(
                search=TavilySearch(
                    max_results=self.max_results,
                    search_depth=self.search_depth,
                    include_domains=TRUSTED_DOMAINS,
                )
            )

        # Load prompt template and bake in ClaimInput schema
        prompt = load_prompt("fact_checker.md")
        input_schema = json.dumps(ClaimInput.model_json_schema(), indent=2, ensure_ascii=False)
        self.prompt_template = prompt.replace("{input_schema}", input_schema)

        # Self-critique settings
        self.critique_model_name = os.getenv("GEMINI_MODEL_SELF_CRITIQUE", "gemini-2.5-flash")
        self.self_critique_enabled = os.getenv("SELF_CRITIQUE_ENABLED", "true").lower() != "false"
        try:
            critique_prompt_raw = load_prompt("self_critique.md")
            critique_schema = json.dumps(SelfCritiqueInput.model_json_schema(), indent=2, ensure_ascii=False)
            self.critique_prompt = critique_prompt_raw.replace("{input_schema}", critique_schema)
        except FileNotFoundError:
            self.critique_prompt = None
            self.self_critique_enabled = False
        self.critique_client = genai.Client(api_key=google_api_key) if self.self_critique_enabled else None

        # Parallel processing settings
        self.parallel_enabled = os.getenv("FACT_CHECK_PARALLEL", "false").lower() == "true"
        self.max_workers = int(os.getenv("FACT_CHECK_MAX_WORKERS", "5"))

        # Recursion limit (avoid infinity loops and high costs)
        # Default to 25 for production; tests should set FACT_CHECK_RECURSION_LIMIT=10 or lower
        self.recursion_limit = int(os.getenv("FACT_CHECK_RECURSION_LIMIT", "35"))

        logger.info(
            f"FactChecker initialized with model: {self.model_name}, "
            f"fallback: {self.fallback_model_name}, "
            f"search_depth: {self.search_depth}, max_results: {self.max_results}, "
            f"parallel: {self.parallel_enabled}, max_workers: {self.max_workers}, "
            f"recursion_limit: {self.recursion_limit}"
        )

    @staticmethod
    def _format_episode_date(date: str) -> str:
        """Extract month and year from episode date string, e.g. '1. März 2026' → 'März 2026'."""
        parts = date.split()
        if parts and parts[0].endswith('.'):
            return ' '.join(parts[1:])
        return date

    def _build_user_message(self, speaker: str, claim: str, context: str = None, episode_date: str | None = None) -> str:
        """Build the user message for a single claim fact-check."""
        return ClaimInput(
            context=context or "",
            sprecher=speaker,
            sendedatum=self._format_episode_date(episode_date) if episode_date else "",
            behauptung=claim,
        ).model_dump_json(indent=2)

    async def check_claim_async(self, speaker: str, claim: str, context: str = None, episode_date: str | None = None) -> Dict[str, Any]:
        """
        Fact-check a single claim using LangGraph ReAct agent with Tavily search (async).

        Args:
            speaker: Name of the person who made the claim
            claim: The claim text to verify
            context: Optional context information (show info, date, source)
            episode_date: Air date of the episode (e.g. "1. März 2026"), used as Sendedatum

        Returns:
            Dictionary with speaker, original_claim, consistency, evidence, sources
        """
        logger.info(f"Checking claim from {speaker}: {claim[:100]}...")

        current_date = datetime.now().strftime("%B %Y")
        system_prompt = self.prompt_template.replace("{current_date}", current_date)
        user_message = self._build_user_message(speaker, claim, context, episode_date=episode_date)

        return await self._check_claim_async(speaker, claim, system_prompt, user_message)

    def check_claim(self, speaker: str, claim: str, context: str = None, episode_date: str | None = None) -> Dict[str, Any]:
        """
        Fact-check a single claim (sync wrapper).

        Args:
            speaker: Name of the person who made the claim
            claim: The claim text to verify
            context: Optional context information
            episode_date: Air date of the episode (e.g. "1. März 2026"), used as Sendedatum

        Returns:
            Dictionary with speaker, original_claim, consistency, evidence, sources

        Note:
            Use check_claim_async() in async contexts to avoid event loop conflicts.
        """
        return asyncio.run(self.check_claim_async(speaker, claim, context=context, episode_date=episode_date))

    async def _check_claim_async(self, speaker: str, claim: str, system_prompt: str, user_message: str) -> Dict[str, Any]:
        """Async implementation of claim checking."""
        # Log first claim check to a file for prompt inspection
        if not FactChecker._first_claim_logged and "PYTEST_CURRENT_TEST" not in os.environ:
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                log_path = os.path.join("logs", "prompt_dumps", f"{timestamp}_fact_checker.txt")
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write("=== SYSTEM PROMPT ===\n")
                    f.write(system_prompt)
                    f.write("\n\n=== USER MESSAGE ===\n")
                    f.write(user_message)
                FactChecker._first_claim_logged = True
                logger.info(f"First fact check prompt dumped to {log_path}")
            except Exception:
                logger.exception("Failed to dump first fact check prompt")

        try:
            agent = create_agent(
                model=self.llm,
                tools=[self.search_tool],
                system_prompt=system_prompt,
                response_format=FactCheckResponse,
            )

            # Run agent via streaming to collect intermediate states for debugging.
            # Use sync stream in a thread (same reason as invoke: ChatGoogleGenerativeAI ainvoke bugs).
            # See: https://github.com/langchain-ai/langchain-google/issues/357
            result, trace, recursion_error = await asyncio.to_thread(
                FactChecker._invoke_with_trace,
                agent,
                {"messages": [{"role": "user", "content": user_message}]},
                {"recursion_limit": self.recursion_limit}
            )

            if recursion_error:
                self._dump_recursion_trace(trace, speaker, claim)
                logger.warning(f"Recursion limit hit for '{speaker}', retrying once...")
                result = await asyncio.to_thread(
                    agent.invoke,
                    {"messages": [{"role": "user", "content": user_message}]},
                    config={"recursion_limit": self.recursion_limit}
                )

            # Handle nested structured_response
            if "structured_response" in result:
                parsed = to_dict(result["structured_response"])
            else:
                # Result might already be flat
                parsed = to_dict(result)

            # Retry once if agent returned no structured response or empty fields
            # This happens when Gemini ignores tool_choice="any" and responds with plain text
            if "structured_response" not in result or (not parsed.get("speaker") and not parsed.get("original_claim")):
                logger.warning(f"Agent returned no structured response for '{speaker}', retrying once...")
                result = await asyncio.to_thread(
                    agent.invoke,
                    {"messages": [{"role": "user", "content": user_message}]},
                    config={"recursion_limit": self.recursion_limit}
                )
                if "structured_response" in result:
                    parsed = to_dict(result["structured_response"])
                else:
                    parsed = to_dict(result)

            # Fallback to input values if still empty after retry
            if not parsed.get("speaker"):
                parsed["speaker"] = speaker
            if not parsed.get("original_claim"):
                parsed["original_claim"] = claim

            # Extract and log cost
            cost_tracker = get_cost_tracker(self.model_name)
            stats = cost_tracker.extract_usage_stats(result)
            cost_tracker.log_claim_cost(
                stats,
                speaker=speaker,
                claim=claim,
                consistency=parsed.get('consistency', 'unknown')
            )
            cost_tracker.log_session_totals()

            logger.info(f"Claim checked: consistency = {parsed.get('consistency', 'unknown')}")

            # Self-critique step
            critique = await self._critique_async(
                claim, parsed.get("consistency", ""), parsed.get("evidence", "")
            )
            parsed["double_check"] = critique.confidence == "low"
            parsed["critique_note"] = critique.reason

            return parsed

        except Exception as e:
            logger.exception("Fact-check failed for claim")
            return {
                "speaker": speaker,
                "original_claim": claim,
                "consistency": "unklar",
                "evidence": f"Fehler bei der Überprüfung: {str(e)}",
                "sources": []
            }

    @staticmethod
    def _invoke_with_trace(agent, input_dict: dict, config: dict):
        """Run agent via streaming, collecting all intermediate states. Returns (result, states, error)."""
        all_states = []
        try:
            for state in agent.stream(input_dict, config=config, stream_mode="values"):
                all_states.append(state)
            return all_states[-1] if all_states else {}, all_states, None
        except GraphRecursionError as e:
            return None, all_states, e

    def _dump_recursion_trace(self, states: list, speaker: str, claim: str) -> None:
        """Dump agent message trace to file when recursion limit is hit."""
        if "PYTEST_CURRENT_TEST" in os.environ:
            return
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path = os.path.join("logs", "prompt_dumps", f"{timestamp}_recursion_trace.txt")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            messages = states[-1].get("messages", []) if states else []
            with open(log_path, "w", encoding="utf-8") as f:
                f.write("=== RECURSION LIMIT HIT ===\n")
                f.write(f"Speaker: {speaker}\n")
                f.write(f"Claim: {claim}\n")
                f.write(f"Recursion limit: {self.recursion_limit}\n")
                f.write(f"Steps collected: {len(states)}\n")
                f.write(f"Messages in last state: {len(messages)}\n\n")
                f.write("=== MESSAGE TRACE ===\n\n")
                for i, msg in enumerate(messages):
                    msg_type = type(msg).__name__
                    content = getattr(msg, "content", "")
                    if isinstance(content, list):
                        content = " ".join(str(c) for c in content)
                    tool_calls = getattr(msg, "tool_calls", [])
                    f.write(f"[{i + 1}] {msg_type}\n")
                    if content:
                        f.write(f"    {str(content)[:500]}\n")
                    for tc in tool_calls:
                        f.write(f"    TOOL CALL: {tc.get('name', '?')}({json.dumps(tc.get('args', {}))[:200]})\n")
                    f.write("\n")
            logger.warning(f"Recursion trace dumped to {log_path}")
        except Exception:
            logger.exception("Failed to dump recursion trace")

    async def _critique_async(self, claim: str, consistency: str, evidence: str) -> SelfCritiqueResponse:
        """Self-critique a verdict for wording sensitivity and confidence."""
        if not self.self_critique_enabled or not self.critique_prompt or not self.critique_client:
            return SelfCritiqueResponse(confidence="high", reason="")

        user_message = SelfCritiqueInput(
            behauptung=claim, urteil=consistency, begruendung=evidence
        ).model_dump_json(indent=2)
        try:
            response = await self.critique_client.aio.models.generate_content(
                model=self.critique_model_name,
                contents=user_message,
                config={
                    "system_instruction": self.critique_prompt,
                    "response_mime_type": "application/json",
                    "response_schema": SelfCritiqueResponse,
                },
            )
            return response.parsed
        except Exception:
            logger.exception("Self-critique failed, using defaults")
            return SelfCritiqueResponse(confidence="high")

    async def check_claims_async(self, claims: List[Dict[str, str]], context: str = None, episode_date: str | None = None) -> List[Dict[str, Any]]:
        """
        Fact-check multiple claims (sequential or parallel based on config, async).

        Args:
            claims: List of claim dictionaries with 'name' and 'claim' keys
            context: Optional context information for all claims
            episode_date: Air date of the episode (e.g. "1. März 2026"), used as Sendedatum

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
            return await self._check_claims_parallel_async(claims, context=context, episode_date=episode_date)
        else:
            return await self._check_claims_sequential_async(claims, context=context, episode_date=episode_date)

    def check_claims(self, claims: List[Dict[str, str]], context: str = None, episode_date: str | None = None) -> List[Dict[str, Any]]:
        """
        Fact-check multiple claims (sync wrapper).

        Args:
            claims: List of claim dictionaries with 'name' and 'claim' keys
            context: Optional context information
            episode_date: Air date of the episode (e.g. "1. März 2026"), used as Sendedatum

        Returns:
            List of fact-check result dictionaries

        Note:
            Use check_claims_async() in async contexts to avoid event loop conflicts.
        """
        return asyncio.run(self.check_claims_async(claims, context=context, episode_date=episode_date))

    async def _check_claims_sequential_async(self, claims: List[Dict[str, str]], context: str = None, episode_date: str | None = None) -> List[Dict[str, Any]]:
        """Process claims one by one (async)."""
        current_date = datetime.now().strftime("%B %Y")
        system_prompt = self.prompt_template.replace("{current_date}", current_date)
        results = []
        for i, claim_data in enumerate(claims):
            logger.info(f"Processing claim {i + 1}/{len(claims)}")
            speaker = claim_data.get("name", "Unknown")
            claim = claim_data.get("claim", "")
            user_message = self._build_user_message(speaker, claim, context, episode_date=episode_date)
            result = await self._check_claim_async(speaker, claim, system_prompt, user_message)
            results.append(result)
        return results

    async def _check_claims_parallel_async(self, claims: List[Dict[str, str]], context: str = None, episode_date: str | None = None) -> List[Dict[str, Any]]:
        """Async implementation of parallel claim checking."""
        semaphore = asyncio.Semaphore(self.max_workers)

        current_date = datetime.now().strftime("%B %Y")
        system_prompt = self.prompt_template.replace("{current_date}", current_date)

        async def check_with_limit(claim_data: Dict[str, str], index: int) -> Dict[str, Any]:
            """Check a single claim with concurrency limiting."""
            async with semaphore:
                speaker = claim_data.get("name", "Unknown")
                claim = claim_data.get("claim", "")
                logger.info(f"Processing claim {index + 1}/{len(claims)}: {claim[:50]}...")
                user_message = self._build_user_message(speaker, claim, context, episode_date=episode_date)
                result = await self._check_claim_async(speaker, claim, system_prompt, user_message)
                logger.info(f"Completed claim {index + 1}/{len(claims)}: {result.get('consistency', 'unknown')}")
                return result

        logger.info(f"Running {len(claims)} claims in parallel (max_concurrency: {self.max_workers})")

        # Run all claims concurrently (semaphore limits actual parallelism)
        results = await asyncio.gather(
            *[check_with_limit(claim, i) for i, claim in enumerate(claims)],
            return_exceptions=False
        )

        return list(results)

