"""
Claim Extraction Service using PydanticAI + Gemini.

Two single-shot typed agents: speaker label resolution and claim extraction,
plus a selection agent for autopilot mode. No tools, no loop.
"""

import os
import asyncio
import logging
from typing import List

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from backend.utils import load_prompt
from backend.lang import CLAIM_NAME_DESCRIPTION, CLAIM_TEXT_DESCRIPTION
from .llm_base import build_model, MODEL_SETTINGS, settings_with_thinking

logger = logging.getLogger(__name__)

# Default model if not specified in environment
DEFAULT_MODEL = "gemini-2.5-flash"

# Auto-check safety net: the selection agent picks all *prüfwürdige* claims per
# block (no fixed target), but we never fan out more than this many fact-checks
# from a single block, to bound cost and pipeline load on unusually dense blocks.
AUTO_SELECT_MAX = int(os.getenv("AUTO_SELECT_MAX", "6"))


class ExtractedClaim(BaseModel):
    """A standalone, decontextualized factual claim."""
    name: str = Field(description=CLAIM_NAME_DESCRIPTION)
    claim: str = Field(description=CLAIM_TEXT_DESCRIPTION)


class ReformulatedClaim(ExtractedClaim):
    """A reformulated live claim plus search queries for the fast checker."""
    search_queries: List[str] = Field(
        default_factory=list,
        description="3–5 kurze deutsche Suchanfragen (Stichworte, keine ganzen Sätze), die "
                    "die Behauptung mit offiziellen Daten überprüfen.",
    )


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
    conversation_type: str = Field(default="", description="Art des Gesprächs: 'debate' (öffentliche Debatte/Talkshow), 'interview' oder 'private' (privates Gespräch).")
    guests: list[str] = Field(description="Teilnehmer des Gesprächs, z. B. ['Caren Miosga (Moderatorin)', 'Heidi Reichinnek (Linke)'] — bei privaten Gesprächen ggf. nur Vornamen.")
    transcript: str = Field(description="Transkript mit generischen Sprecherbezeichnungen")


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
    """Extracts verifiable claims from transcripts using PydanticAI + Gemini."""

    def __init__(self):
        self.model_name = os.getenv("GEMINI_MODEL_CLAIM_EXTRACTION", DEFAULT_MODEL)
        model = build_model(self.model_name)

        # Input fields are described in the prompts themselves; no schema baking needed.
        self.claim_extractor = Agent(
            model,
            output_type=ClaimList,
            instructions=load_prompt("claim_extraction.md"),
            model_settings=MODEL_SETTINGS,
        )

        # Selection agent: same ClaimList schema, different prompt. It picks all
        # check-worthy claims (no fixed count); the cap is applied in code below.
        self.selection_agent = Agent(
            model,
            output_type=ClaimList,
            instructions=load_prompt("claim_selection.md"),
            model_settings=MODEL_SETTINGS,
        )

        # Speaker label resolution agent (optional — only if prompt exists).
        try:
            sl_prompt = load_prompt("speaker_labels.md")
            self.speaker_resolver = Agent(
                model,
                output_type=ResolvedTranscript,
                instructions=sl_prompt,
                model_settings=MODEL_SETTINGS,
            )
        except FileNotFoundError:
            self.speaker_resolver = None

        # Window gate agent (live streaming lane): a separate, faster/cheaper model
        # that decides per small window whether there is a check-worthy claim and
        # extracts it. Kept independent so the batch extractor above is untouched.
        self.window_model_name = os.getenv("GEMINI_MODEL_WINDOW_GATE", "gemini-3.5-flash-lite")
        self.window_gate = Agent(
            build_model(self.window_model_name),
            output_type=ClaimList,
            instructions=load_prompt(
                "claim_extraction_streaming.md",
                fallback=load_prompt("claim_extraction.md"),
            ),
            model_settings=MODEL_SETTINGS,
        )

        # Reformulation agent (live streaming lane, Jev gate): does NOT judge
        # check-worthiness (the Jev gate already did) — it rewrites a single gated
        # sentence into a standalone, decontextualized claim, assigns the speaker and
        # writes the search queries for the fast checker. Used by ``JevGate`` in
        # services/gate.py. Flash, not flash-lite: the queries decide what the fast
        # checker gets to see.
        self.reformulate_model_name = os.getenv("GEMINI_MODEL_REFORMULATE", "gemini-3.6-flash")
        self.reformulator = Agent(
            build_model(self.reformulate_model_name),
            output_type=ReformulatedClaim,
            instructions=load_prompt(
                "claim_reformulation.md",
                fallback=load_prompt("claim_extraction_streaming.md",
                                     fallback=load_prompt("claim_extraction.md")),
            ),
            model_settings=settings_with_thinking(os.getenv("GEMINI_THINKING_REFORMULATE", "low")),
        )

        logger.info(
            f"ClaimExtractor initialized (extraction={self.model_name}, "
            f"window_gate={self.window_model_name}, reformulate={self.reformulate_model_name})"
        )

    async def _resolve_speaker_labels_async(self, transcript: str, guests: list[str], conversation_type: str = "") -> str:
        """Step 1: Identify speaker label->name mappings and apply them to the transcript."""
        user_message = SpeakerLabelsInput(
            conversation_type=conversation_type, guests=guests, transcript=transcript
        ).model_dump_json(indent=2)
        result = await self.speaker_resolver.run(user_message)
        # Replace longest labels first so an overlapping short label (e.g. "Sprecher A")
        # cannot corrupt a longer one (e.g. "Sprecher AB").
        for m in sorted(result.output.mappings, key=lambda x: len(x.label), reverse=True):
            transcript = transcript.replace(m.label, m.name)
        return transcript

    async def resolve_labels_async(self, transcript: str, guests: list[str], conversation_type: str = "") -> str:
        """Resolve generic speaker labels to real names. Returns transcript unchanged if no resolver."""
        if self.speaker_resolver:
            return await self._resolve_speaker_labels_async(transcript, guests, conversation_type)
        return transcript

    async def resolve_speaker_map_async(self, transcript: str, guests: list[str], conversation_type: str = "") -> dict[str, str]:
        """Return a ``{label: name}`` mapping for a transcript, without applying it.

        Used by the live streaming lane, which resolves labels once enough transcript has
        accrued and caches the mapping (labels are stable within a session), rather than
        rewriting text. Returns an empty dict when no resolver or nothing to map.
        """
        if not self.speaker_resolver or not transcript or not transcript.strip():
            return {}
        user_message = SpeakerLabelsInput(
            conversation_type=conversation_type, guests=guests, transcript=transcript
        ).model_dump_json(indent=2)
        result = await self.speaker_resolver.run(user_message)
        return {m.label: m.name for m in result.output.mappings if m.label and m.name}

    async def extract_claims_async(self, resolved_transcript: str, guests: list[str], context: str = "", previous_context: str | None = None, conversation_type: str = "", excluded_speakers: list[str] | None = None) -> List[ExtractedClaim]:
        """Extract claims from an already-resolved transcript. Skips speaker label resolution.

        This is the preferred entry point for the audio pipeline (called after resolve_labels_async).
        """
        logger.info(f"Extracting claims from resolved transcript ({len(resolved_transcript)} chars)")
        user_message = ClaimExtractionInput(
            conversation_type=conversation_type, guests=guests, context=context,
            excluded_speakers=excluded_speakers or [],
            transcript=resolved_transcript, previous_block_ending=previous_context,
        ).model_dump_json(indent=2)
        result = await self.claim_extractor.run(user_message)
        logger.info(f"Extraction complete: {len(result.output.claims)} claims found")
        return result.output.claims

    async def extract_async(self, transcript: str, guests: list[str], context: str = "", previous_context: str | None = None, conversation_type: str = "", excluded_speakers: list[str] | None = None) -> List[ExtractedClaim]:
        """Extract claims, resolving speaker labels first (text-block pipeline entry point)."""
        logger.info(f"Extracting claims from transcript ({len(transcript)} chars)")
        if self.speaker_resolver:
            transcript = await self._resolve_speaker_labels_async(transcript, guests, conversation_type)
            logger.info(f"Speaker labels resolved ({len(transcript)} chars)")
        return await self.extract_claims_async(transcript, guests, context=context, previous_context=previous_context, conversation_type=conversation_type, excluded_speakers=excluded_speakers)

    def extract(self, transcript: str, guests: list[str], context: str = "", previous_context: str | None = None, conversation_type: str = "", excluded_speakers: list[str] | None = None) -> List[ExtractedClaim]:
        """Sync wrapper for extract_async()."""
        return asyncio.run(self.extract_async(transcript, guests, context=context, previous_context=previous_context, conversation_type=conversation_type, excluded_speakers=excluded_speakers))

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
        fast/cheap window-gate agent, not the batch extractor. Speaker labels are
        assumed already resolved by the streaming layer (no resolve step here).
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

    async def select_async(self, claims: List[dict], max_claims: int = AUTO_SELECT_MAX) -> List[dict]:
        """Select all check-worthy claims (autopilot mode).

        The agent decides how many claims are worth checking based on quality, not
        a fixed target. ``max_claims`` is only a safety cap to bound fan-out on
        unusually dense blocks; it normally does not bind.
        """
        logger.info(f"Autopilot: selecting check-worthy claims from {len(claims)} (cap {max_claims})...")
        claims_text = "\n".join(
            f"{i + 1}. [{c.get('name', '?')}]: {c.get('claim', '')}"
            for i, c in enumerate(claims)
        )
        user_message = f"Behauptungen:\n{claims_text}"
        try:
            result = await self.selection_agent.run(user_message)
            selected = [{"name": c.name, "claim": c.claim} for c in result.output.claims]
            logger.info(f"Autopilot: selected {len(selected)} claims (cap {max_claims})")
            return selected[:max_claims]
        except Exception:
            logger.exception("Claim selection failed, falling back to all claims (capped)")
            return claims[:max_claims]
