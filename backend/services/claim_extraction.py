"""
Claim Extraction Service using PydanticAI + Gemini.

Two single-shot typed agents: speaker label resolution and claim extraction,
plus a selection agent for autopilot mode. No tools, no loop.
"""

import os
import json
import asyncio
import logging
from dataclasses import dataclass
from typing import List

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from backend.utils import load_prompt
from backend.lang import CLAIM_NAME_DESCRIPTION, CLAIM_TEXT_DESCRIPTION
from .llm_base import build_model, MODEL_SETTINGS

logger = logging.getLogger(__name__)

# Default model if not specified in environment
DEFAULT_MODEL = "gemini-2.5-flash"


class ExtractedClaim(BaseModel):
    """A standalone, decontextualized factual claim."""
    name: str = Field(description=CLAIM_NAME_DESCRIPTION)
    claim: str = Field(description=CLAIM_TEXT_DESCRIPTION)


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
    guests: list[str] = Field(description="Teilnehmer der Sendung, z. B. ['Caren Miosga (Moderatorin)', 'Heidi Reichinnek (Linke)']")
    transcript: str = Field(description="Transkript mit generischen Sprecherbezeichnungen")


class ClaimExtractionInput(BaseModel):
    """Input for claim extraction from a transcript."""
    date: str = Field(description="Sendedatum, z. B. 'Oktober 2025'")
    guests: list[str] = Field(description="Teilnehmer der Sendung")
    context: str = Field(default="", description="Thematischer Hintergrund der Sendung")
    transcript: str = Field(description="Transkript zur Analyse")
    previous_block_ending: str | None = Field(default=None, description="Letzte Zeilen des vorherigen Transkriptblocks zur Gewährleistung der Kontinuität")


@dataclass
class SelectionDeps:
    """Runtime dependency for the selection agent — templates {max_claims}."""
    max_claims: int


class ClaimExtractor:
    """Extracts verifiable claims from transcripts using PydanticAI + Gemini."""

    def __init__(self):
        self.model_name = os.getenv("GEMINI_MODEL_CLAIM_EXTRACTION", DEFAULT_MODEL)
        model = build_model(self.model_name)

        # Bake the input schema into each prompt (placeholder {input_schema}).
        prompt = load_prompt("claim_extraction.md")
        extraction_schema = json.dumps(ClaimExtractionInput.model_json_schema(), indent=2, ensure_ascii=False)
        self.claim_extractor = Agent(
            model,
            output_type=ClaimList,
            instructions=prompt.replace("{input_schema}", extraction_schema),
            model_settings=MODEL_SETTINGS,
        )

        # Selection agent: same ClaimList schema, different prompt, {max_claims} per run.
        self.selection_prompt_template = load_prompt("claim_selection.md")
        self.selection_agent = Agent(
            model,
            output_type=ClaimList,
            deps_type=SelectionDeps,
            model_settings=MODEL_SETTINGS,
        )

        @self.selection_agent.instructions
        def _selection_instructions(ctx: RunContext[SelectionDeps]) -> str:
            return self.selection_prompt_template.replace("{max_claims}", str(ctx.deps.max_claims))

        # Speaker label resolution agent (optional — only if prompt exists).
        try:
            sl_prompt = load_prompt("speaker_labels.md")
            sl_schema = json.dumps(SpeakerLabelsInput.model_json_schema(), indent=2, ensure_ascii=False)
            self.speaker_resolver = Agent(
                model,
                output_type=ResolvedTranscript,
                instructions=sl_prompt.replace("{input_schema}", sl_schema),
                model_settings=MODEL_SETTINGS,
            )
        except FileNotFoundError:
            self.speaker_resolver = None

        logger.info(f"ClaimExtractor initialized with model: {self.model_name}")

    async def _resolve_speaker_labels_async(self, transcript: str, guests: list[str]) -> str:
        """Step 1: Identify speaker label->name mappings and apply them to the transcript."""
        user_message = SpeakerLabelsInput(guests=guests, transcript=transcript).model_dump_json(indent=2)
        result = await self.speaker_resolver.run(user_message)
        for m in result.output.mappings:
            transcript = transcript.replace(m.label, m.name)
        return transcript

    async def resolve_labels_async(self, transcript: str, guests: list[str]) -> str:
        """Resolve generic speaker labels to real names. Returns transcript unchanged if no resolver."""
        if self.speaker_resolver:
            return await self._resolve_speaker_labels_async(transcript, guests)
        return transcript

    async def extract_claims_async(self, resolved_transcript: str, guests: list[str], date: str = "", context: str = "", previous_context: str | None = None) -> List[ExtractedClaim]:
        """Extract claims from an already-resolved transcript. Skips speaker label resolution.

        This is the preferred entry point for the audio pipeline (called after resolve_labels_async).
        """
        logger.info(f"Extracting claims from resolved transcript ({len(resolved_transcript)} chars)")
        user_message = ClaimExtractionInput(
            date=date, guests=guests, context=context,
            transcript=resolved_transcript, previous_block_ending=previous_context,
        ).model_dump_json(indent=2)
        result = await self.claim_extractor.run(user_message)
        logger.info(f"Extraction complete: {len(result.output.claims)} claims found")
        return result.output.claims

    async def extract_async(self, transcript: str, guests: list[str], date: str = "", context: str = "", previous_context: str | None = None) -> List[ExtractedClaim]:
        """Extract claims, resolving speaker labels first (text-block pipeline entry point)."""
        logger.info(f"Extracting claims from transcript ({len(transcript)} chars)")
        if self.speaker_resolver:
            transcript = await self._resolve_speaker_labels_async(transcript, guests)
            logger.info(f"Speaker labels resolved ({len(transcript)} chars)")
        return await self.extract_claims_async(transcript, guests, date=date, context=context, previous_context=previous_context)

    def extract(self, transcript: str, guests: list[str], date: str = "", context: str = "", previous_context: str | None = None) -> List[ExtractedClaim]:
        """Sync wrapper for extract_async()."""
        return asyncio.run(self.extract_async(transcript, guests, date=date, context=context, previous_context=previous_context))

    async def select_async(self, claims: List[dict], max_claims: int = 3) -> List[dict]:
        """Select the top N most fact-checkable claims (autopilot mode)."""
        logger.info(f"Autopilot: selecting up to {max_claims} relevant claims from {len(claims)}...")
        claims_text = "\n".join(
            f"{i + 1}. [{c.get('name', '?')}]: {c.get('claim', '')}"
            for i, c in enumerate(claims)
        )
        user_message = f"Behauptungen:\n{claims_text}"
        try:
            result = await self.selection_agent.run(user_message, deps=SelectionDeps(max_claims=max_claims))
            selected = [{"name": c.name, "claim": c.claim} for c in result.output.claims]
            logger.info(f"Autopilot: selected {len(selected)} claims")
            return selected[:max_claims]
        except Exception:
            logger.exception("Claim selection failed, falling back to all claims (capped)")
            return claims[:max_claims]
