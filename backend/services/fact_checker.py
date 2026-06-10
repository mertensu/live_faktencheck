"""
Fact Checker Service using PydanticAI with Gemini and Tavily Search.

A typed ReAct-style agent (reason -> tavily_search -> reason -> verdict) plus a
separate self-critique agent that annotates the verdict without gating it.
"""

import os
import json
import asyncio
import logging
from typing import List, Dict, Any, Literal
from datetime import datetime

from pydantic import BaseModel, Field
from pydantic_ai import Agent, UsageLimits, UsageLimitExceeded

from backend.utils import load_prompt
from backend.lang import (
    SOURCE_URL_DESCRIPTION,
    SOURCE_TITLE_DESCRIPTION,
    CONSISTENCY_DESCRIPTION,
    EVIDENCE_DESCRIPTION,
    SOURCES_DESCRIPTION,
    CRITIQUE_CONFIDENCE_DESCRIPTION,
    CRITIQUE_REASON_DESCRIPTION,
)
from .llm_base import build_model, MODEL_SETTINGS
from .search import tavily_search

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-pro"


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


class FactChecker:
    """Fact-checks claims using a PydanticAI agent with Gemini and Tavily."""

    def __init__(self):
        self.model_name = os.getenv("GEMINI_MODEL_FACT_CHECKER", DEFAULT_MODEL)
        self.fallback_model_name = os.getenv("GEMINI_MODEL_FACT_CHECKER_FALLBACK", "gemini-3-flash-preview")

        # Bound the agent loop. Env name kept for backwards compatibility with existing .env/tests.
        self.request_limit = int(os.getenv("FACT_CHECK_RECURSION_LIMIT", "35"))

        # Bake the input schema into the prompt; {current_date} is filled per run.
        prompt = load_prompt("fact_checker.md")
        input_schema = json.dumps(ClaimInput.model_json_schema(), indent=2, ensure_ascii=False)
        self.prompt_template = prompt.replace("{input_schema}", input_schema)

        self.agent = Agent(
            build_model(self.model_name, self.fallback_model_name),
            output_type=FactCheckResponse,
            tools=[tavily_search],
            model_settings=MODEL_SETTINGS,
            retries=2,
        )

        @self.agent.instructions
        def _fact_check_instructions() -> str:
            current_date = datetime.now().strftime("%B %Y")
            return self.prompt_template.replace("{current_date}", current_date)

        # Self-critique agent (separate, annotates only; never gates the verdict).
        self.critique_model_name = os.getenv("GEMINI_MODEL_SELF_CRITIQUE", "gemini-2.5-flash")
        self.self_critique_enabled = os.getenv("SELF_CRITIQUE_ENABLED", "true").lower() != "false"
        self.critique_agent = None
        if self.self_critique_enabled:
            try:
                critique_prompt = load_prompt("self_critique.md")
                critique_schema = json.dumps(SelfCritiqueInput.model_json_schema(), indent=2, ensure_ascii=False)
                self.critique_agent = Agent(
                    build_model(self.critique_model_name),
                    output_type=SelfCritiqueResponse,
                    instructions=critique_prompt.replace("{input_schema}", critique_schema),
                    model_settings=MODEL_SETTINGS,
                )
            except FileNotFoundError:
                self.self_critique_enabled = False

        self.parallel_enabled = os.getenv("FACT_CHECK_PARALLEL", "false").lower() == "true"
        self.max_workers = int(os.getenv("FACT_CHECK_MAX_WORKERS", "5"))

        logger.info(
            f"FactChecker initialized with model: {self.model_name}, "
            f"fallback: {self.fallback_model_name}, request_limit: {self.request_limit}, "
            f"parallel: {self.parallel_enabled}, max_workers: {self.max_workers}"
        )

    @staticmethod
    def _format_episode_date(date: str) -> str:
        """Extract month and year, e.g. '1. März 2026' → 'März 2026'."""
        parts = date.split()
        if parts and parts[0].endswith("."):
            return " ".join(parts[1:])
        return date

    def _build_user_message(self, speaker: str, claim: str, context: str = None, episode_date: str | None = None) -> str:
        return ClaimInput(
            context=context or "",
            sprecher=speaker,
            sendedatum=self._format_episode_date(episode_date) if episode_date else "",
            behauptung=claim,
        ).model_dump_json(indent=2)

    async def check_claim_async(self, speaker: str, claim: str, context: str = None, episode_date: str | None = None) -> Dict[str, Any]:
        """Fact-check a single claim (async)."""
        logger.info(f"Checking claim from {speaker}: {claim[:100]}...")
        user_message = self._build_user_message(speaker, claim, context, episode_date=episode_date)
        return await self._check_claim_async(speaker, claim, user_message)

    def check_claim(self, speaker: str, claim: str, context: str = None, episode_date: str | None = None) -> Dict[str, Any]:
        """Sync wrapper for check_claim_async()."""
        return asyncio.run(self.check_claim_async(speaker, claim, context=context, episode_date=episode_date))

    async def _check_claim_async(self, speaker: str, claim: str, user_message: str) -> Dict[str, Any]:
        limits = UsageLimits(request_limit=self.request_limit)
        try:
            try:
                result = await self.agent.run(user_message, usage_limits=limits)
            # Retry once with a fresh request counter (each run() tracks usage independently).
            except UsageLimitExceeded:
                logger.warning(f"Usage limit hit for '{speaker}', retrying once...")
                result = await self.agent.run(user_message, usage_limits=limits)

            parsed = result.output.model_dump()
            if not parsed.get("speaker"):
                parsed["speaker"] = speaker
            if not parsed.get("original_claim"):
                parsed["original_claim"] = claim

            logger.info(f"Claim checked: consistency = {parsed.get('consistency', 'unknown')}")

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
                "sources": [],
                "double_check": False,
                "critique_note": "",
            }

    async def _critique_async(self, claim: str, consistency: str, evidence: str) -> SelfCritiqueResponse:
        """Self-critique a verdict for confidence. Never blocks or retries the verdict."""
        if not self.self_critique_enabled or not self.critique_agent:
            return SelfCritiqueResponse(confidence="high", reason="")
        user_message = SelfCritiqueInput(
            behauptung=claim, urteil=consistency, begruendung=evidence
        ).model_dump_json(indent=2)
        try:
            result = await self.critique_agent.run(user_message)
            return result.output
        except Exception:
            logger.exception("Self-critique failed, using defaults")
            return SelfCritiqueResponse(confidence="high")

    async def check_claims_async(self, claims: List[Dict[str, str]], context: str = None, episode_date: str | None = None) -> List[Dict[str, Any]]:
        """Fact-check multiple claims (sequential or parallel based on config)."""
        if not claims:
            return []
        logger.info(f"Checking {len(claims)} claims ({'parallel' if self.parallel_enabled else 'sequential'})")
        if self.parallel_enabled:
            return await self._check_claims_parallel_async(claims, context=context, episode_date=episode_date)
        return await self._check_claims_sequential_async(claims, context=context, episode_date=episode_date)

    def check_claims(self, claims: List[Dict[str, str]], context: str = None, episode_date: str | None = None) -> List[Dict[str, Any]]:
        """Sync wrapper for check_claims_async()."""
        return asyncio.run(self.check_claims_async(claims, context=context, episode_date=episode_date))

    async def _check_claims_sequential_async(self, claims: List[Dict[str, str]], context: str = None, episode_date: str | None = None) -> List[Dict[str, Any]]:
        results = []
        for i, claim_data in enumerate(claims):
            logger.info(f"Processing claim {i + 1}/{len(claims)}")
            speaker = claim_data.get("name", "Unknown")
            claim = claim_data.get("claim", "")
            user_message = self._build_user_message(speaker, claim, context, episode_date=episode_date)
            results.append(await self._check_claim_async(speaker, claim, user_message))
        return results

    async def _check_claims_parallel_async(self, claims: List[Dict[str, str]], context: str = None, episode_date: str | None = None) -> List[Dict[str, Any]]:
        semaphore = asyncio.Semaphore(self.max_workers)

        async def check_with_limit(claim_data, index):
            async with semaphore:
                speaker = claim_data.get("name", "Unknown")
                claim = claim_data.get("claim", "")
                logger.info(f"Processing claim {index + 1}/{len(claims)}: {claim[:50]}...")
                user_message = self._build_user_message(speaker, claim, context, episode_date=episode_date)
                result = await self._check_claim_async(speaker, claim, user_message)
                logger.info(f"Completed claim {index + 1}/{len(claims)}: {result.get('consistency', 'unknown')}")
                return result

        logger.info(f"Running {len(claims)} claims in parallel (max_concurrency: {self.max_workers})")
        results = await asyncio.gather(
            *[check_with_limit(claim, i) for i, claim in enumerate(claims)],
            return_exceptions=False,
        )
        return list(results)
