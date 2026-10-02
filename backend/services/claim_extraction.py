"""
Claim Extraction Service using PydanticAI + Gemini (live lane).

Two single-shot typed agents: the window gate (does a small window hold a
check-worthy claim?) and the reformulator (turns a gated sentence into a
standalone claim plus search queries). No tools, no loop.
"""

import os
import logging
from typing import List

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from backend.utils import load_prompt
from backend.lang import CLAIM_NAME_DESCRIPTION, CLAIM_TEXT_DESCRIPTION
from .llm_base import build_model, MODEL_SETTINGS, settings_with_thinking

logger = logging.getLogger(__name__)


class ExtractedClaim(BaseModel):
    """A standalone, decontextualized factual claim."""
    name: str = Field(description=CLAIM_NAME_DESCRIPTION)
    claim: str = Field(description=CLAIM_TEXT_DESCRIPTION)


class ReformulatedClaim(ExtractedClaim):
    """A reformulated live claim plus search queries for the fast checker."""
    search_queries: List[str] = Field(
        default_factory=list,
        description="Genau 5 kurze deutsche Suchanfragen (Stichworte, keine ganzen Sätze), je "
                    "aus einem anderen Blickwinkel: Kern, Datenquelle, Entwicklung, Maßstab, "
                    "Einordnung.",
    )


class ClaimList(BaseModel):
    """List of extracted factual claims."""
    claims: List[ExtractedClaim]


class ReformulationInput(BaseModel):
    """Input for reformulating a single, already-gated sentence into a standalone claim."""
    sentence: str = Field(description="Der bereits als prüfwürdig erkannte Satz, der umformuliert werden soll.")
    speaker: str = Field(default="", description="Sprecher des Satzes (Label oder Eigenname), sofern bekannt.")
    guests: list[str] = Field(default_factory=list, description="Teilnehmer des Gesprächs")
    context: str = Field(default="", description="Thematischer Hintergrund des Gesprächs")
    previous_context: str | None = Field(default=None, description="Vorheriger Gesprächsverlauf zur Auflösung von Pronomen/Bezügen")


class ClaimExtractionInput(BaseModel):
    """Input for claim extraction from a transcript."""
    conversation_type: str = Field(default="", description="Art des Gesprächs: 'debate' (öffentliche Debatte/Talkshow), 'interview' oder 'private' (privates Gespräch).")
    guests: list[str] = Field(description="Teilnehmer des Gesprächs")
    context: str = Field(default="", description="Thematischer Hintergrund des Gesprächs")
    excluded_speakers: list[str] = Field(default_factory=list, description="Namen von Personen, deren Aussagen NICHT extrahiert werden sollen (z. B. Moderator:in). Leere Liste = niemand wird ausgeschlossen.")
    transcript: str = Field(description="Transkript zur Analyse")
    previous_block_ending: str | None = Field(default=None, description="Letzte Zeilen des vorherigen Transkriptblocks zur Gewährleistung der Kontinuität")


class ClaimExtractor:
    """Gates and reformulates live transcript windows using PydanticAI + Gemini."""

    def __init__(self):
        # Window gate agent (live streaming lane): a separate, faster/cheaper model
        # that decides per small window whether there is a check-worthy claim and
        # extracts it.
        self.window_model_name = os.getenv("GEMINI_MODEL_WINDOW_GATE", "gemini-3.5-flash-lite")
        self.window_gate = Agent(
            build_model(self.window_model_name),
            output_type=ClaimList,
            instructions=load_prompt("claim_extraction_streaming.md"),
            model_settings=MODEL_SETTINGS,
        )

        # Reformulation agent (live streaming lane, Jev gate): does NOT judge
        # check-worthiness (the Jev gate already did) — it rewrites a single gated
        # sentence into a standalone, decontextualized claim, assigns the speaker and
        # writes the search queries for the fast checker. Used by ``JevGate`` in
        # services/gate.py. The queries decide what the fast checker gets to see:
        # GPT-6 Luna (Requesty, EU) with medium reasoning writes five queries from fixed
        # angles, which made verdicts stable across runs (13/15 vs 10/15) for ~0.5 s.
        self.reformulate_model_name = os.getenv("GEMINI_MODEL_REFORMULATE", "gpt-6-luna@eu")
        reformulate_thinking = os.getenv("GEMINI_THINKING_REFORMULATE", "medium")
        self.reformulator = Agent(
            build_model(self.reformulate_model_name, thinking=reformulate_thinking),
            output_type=ReformulatedClaim,
            instructions=load_prompt("claim_reformulation.md"),
            model_settings=settings_with_thinking(reformulate_thinking),
        )

        logger.info(
            f"ClaimExtractor initialized (window_gate={self.window_model_name}, reformulate={self.reformulate_model_name})"
        )

    async def extract_window_async(
        self,
        window_text: str,
        guests: list[str],
        context: str = "",
        conversation_type: str = "",
        excluded_speakers: list[str] | None = None,
        previous_context: str | None = None,
    ) -> List[ExtractedClaim]:
        """Live gate: extract check-worthy claims from a *small* window (1–3 sentences).

        Returns an empty list when the window holds nothing check-worthy. Uses the
        fast/cheap window-gate agent. Speaker labels are assumed already resolved by
        the streaming layer (no resolve step here).
        """
        if not window_text or not window_text.strip():
            return []
        user_message = ClaimExtractionInput(
            conversation_type=conversation_type, guests=guests, context=context,
            excluded_speakers=excluded_speakers or [],
            transcript=window_text, previous_block_ending=previous_context,
        ).model_dump_json(indent=2)
        result = await self.window_gate.run(user_message)
        logger.info(f"Window gate: {len(result.output.claims)} claim(s) in window ({len(window_text)} chars)")
        return result.output.claims

    async def reformulate_claim_async(
        self,
        sentence: str,
        speaker: str = "",
        guests: list[str] | None = None,
        context: str = "",
        previous_context: str | None = None,
    ) -> ReformulatedClaim | None:
        """Rewrite one already-gated sentence into a standalone, decontextualized claim.

        This does NOT decide check-worthiness or importance (the Jev gate did both); it
        resolves pronouns/references, assigns/corrects the speaker name against
        ``guests`` and writes search queries for the fast checker. Returns ``None`` for
        empty input.
        """
        if not sentence or not sentence.strip():
            return None
        user_message = ReformulationInput(
            sentence=sentence, speaker=speaker, guests=guests or [],
            context=context, previous_context=previous_context,
        ).model_dump_json(indent=2)
        result = await self.reformulator.run(user_message)
        return result.output
