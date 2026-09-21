"""
Claim gate — the seam that decides whether a window of streamed text contains a
check-worthy claim (and extracts it).

Two implementations sit behind the ``ClaimGate`` protocol, selected by ``CLAIM_GATE``:

- ``ExtractorGate`` (default): one flash-lite window agent both decides *and* extracts.
- ``JevGate`` (``CLAIM_GATE=jev``): a cheap, calibrated per-sentence decision model
  (TypeSafe's Jev via Requesty) decides check-worthiness; only the hits are then handed
  to a flash-lite call that merely *reformulates* them into standalone claims. This keeps
  the expensive LLM off every sentence and out of the check-worthiness judgment — Jev is
  cheaper and, in benchmarking, better calibrated than the flash-lite window gate, which
  was too conservative (0 claims over many windows). See benchmarks/jev_gate_bench.py.

The seam is a thin protocol so either can be dropped in without touching the streaming
layer.
"""

import os
import re
import json
import asyncio
import logging
from typing import List, Protocol, runtime_checkable

from .claim_extraction import ExtractedClaim, ClaimExtractor

logger = logging.getLogger(__name__)


@runtime_checkable
class ClaimGate(Protocol):
    """Given a short text window, return check-worthy claims (empty if none)."""

    async def gate(
        self,
        window_text: str,
        guests: list[str],
        context: str = "",
        conversation_type: str = "",
        excluded_speakers: list[str] | None = None,
        previous_context: str | None = None,
    ) -> List[ExtractedClaim]: ...


class ExtractorGate:
    """Default ``ClaimGate``: runs the extractor's flash-lite window agent."""

    def __init__(self, extractor: ClaimExtractor):
        self._extractor = extractor

    async def gate(
        self,
        window_text: str,
        guests: list[str],
        context: str = "",
        conversation_type: str = "",
        excluded_speakers: list[str] | None = None,
        previous_context: str | None = None,
    ) -> List[ExtractedClaim]:
        return await self._extractor.extract_window_async(
            window_text,
            guests,
            context=context,
            conversation_type=conversation_type,
            excluded_speakers=excluded_speakers,
            previous_context=previous_context,
        )


# --- Jev per-sentence scorer -------------------------------------------------

# Jev's yes/no ("noul") question: does this sentence hold a verifiable factual claim?
# The sentence itself is the "state" (message content); Jev returns a calibrated prob.
_JEV_QUESTION = {
    "claim": {
        "type": "noul",
        "instructions": "Enthält dieser Satz eine überprüfbare Tatsachenbehauptung, die man faktenchecken könnte?",
        "criteria": {
            "true": "Überprüfbarer Tatsachenkern: Zahl, Statistik, Datum, historisches oder aktuelles Faktum, konkrete Aussage über die Realität (wer/was/wann).",
            "false": "Reine Meinung, Wertung, Absicht, Forderung, Frage, Begrüßung oder Floskel ohne überprüfbaren Tatsachenkern.",
        },
    }
}


def _extract_prob(value) -> float | None:
    """Pull the yes-probability out of Jev's nested ``{"claim": {"noul": p}}`` answer."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for k in ("noul", "value", "probability", "prob", "yes"):
            if isinstance(value.get(k), (int, float)):
                return float(value[k])
    return None


class JevScorer:
    """Thin async wrapper over Jev (Requesty, OpenAI-compatible).

    ``score`` returns a calibrated yes-probability in [0, 1] that the sentence contains a
    verifiable factual claim, or ``None`` if the call fails or the answer can't be parsed.
    The client is built lazily so importing this module never requires a key or network.
    """

    def __init__(self, model: str | None = None):
        self.model = model or os.getenv("JEV_MODEL", "typesafe/jev-1.13.0")
        self._client = None

    @staticmethod
    def is_configured() -> bool:
        return bool(os.getenv("REQUESTY_API_KEY"))

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=os.getenv("REQUESTY_API_KEY"),
                base_url=os.getenv("REQUESTY_BASE_URL", "https://router.requesty.ai/v1"),
            )
        return self._client

    async def score(self, sentence: str) -> float | None:
        try:
            resp = await self._get_client().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": sentence}],
                response_format={"type": "questions", "questions": _JEV_QUESTION},
            )
            raw = resp.choices[0].message.content or ""
            return _extract_prob(json.loads(raw).get("claim"))
        except Exception:
            logger.exception("Jev scoring failed for sentence; treating as skip")
            return None


# --- Jev gate ----------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _split_speaker(line: str) -> tuple[str, str]:
    """Split a ``"Speaker: text"`` window line into (speaker, text).

    The streaming layer prefixes finalized turns with ``"{label}: "``. If no such prefix
    is present, the whole line is treated as text with an empty speaker.
    """
    m = re.match(r"^\s*([^:\n]{1,60}?):\s+(.*)$", line, re.DOTALL)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", line.strip()


class JevGate:
    """``ClaimGate`` that gates per sentence with Jev, then reformulates the hits.

    Pipeline per window:
      1. Split the window into (speaker, sentence) pairs.
      2. Score every sentence with Jev, concurrently. ``p >= CHECK_HI`` is a hit; the
         grey zone (``SKIP_LO < p < CHECK_HI``) and misses are skipped conservatively.
      3. For each hit, a cheap flash-lite call reformulates the sentence into a standalone
         claim (pronouns resolved from rolling context, speaker assigned). Jev already
         decided check-worthiness — this step does not re-judge it.
    """

    def __init__(self, extractor: ClaimExtractor, scorer: JevScorer | None = None):
        self._extractor = extractor
        self._scorer = scorer or JevScorer()
        self.check_hi = float(os.getenv("JEV_CHECK_THRESHOLD", "0.85"))
        self.skip_lo = float(os.getenv("JEV_SKIP_THRESHOLD", "0.30"))

    async def gate(
        self,
        window_text: str,
        guests: list[str],
        context: str = "",
        conversation_type: str = "",
        excluded_speakers: list[str] | None = None,
        previous_context: str | None = None,
    ) -> List[ExtractedClaim]:
        if not window_text or not window_text.strip():
            return []

        excluded = {s.strip().casefold() for s in (excluded_speakers or []) if s.strip()}

        # Flatten the window into (speaker, sentence) pairs, keeping order for context.
        pairs: list[tuple[str, str]] = []
        for line in window_text.splitlines():
            if not line.strip():
                continue
            speaker, text = _split_speaker(line)
            if speaker and speaker.casefold() in excluded:
                continue
            for sentence in _split_sentences(text):
                pairs.append((speaker, sentence))

        if not pairs:
            return []

        scores = await asyncio.gather(*(self._scorer.score(s) for _, s in pairs))

        claims: List[ExtractedClaim] = []
        rolling = previous_context  # last sentence(s) seen, for pronoun resolution
        for (speaker, sentence), p in zip(pairs, scores):
            if p is not None and p >= self.check_hi:
                try:
                    claim = await self._extractor.reformulate_claim_async(
                        sentence,
                        speaker=speaker,
                        guests=guests,
                        context=context,
                        previous_context=rolling,
                    )
                except Exception:
                    logger.exception("Reformulation failed for gated sentence")
                    claim = None
                if claim and (claim.claim or "").strip():
                    claims.append(claim)
            # Every sentence (hit or not) extends the rolling context for the next one.
            rolling = f"{speaker}: {sentence}" if speaker else sentence

        logger.info(
            f"JevGate: {len(claims)} claim(s) from {len(pairs)} sentence(s) "
            f"(check>={self.check_hi})"
        )
        return claims


def build_gate(extractor: ClaimExtractor) -> ClaimGate:
    """Pick the gate implementation from ``CLAIM_GATE`` (default: the extractor gate).

    ``CLAIM_GATE=jev`` selects the Jev per-sentence gate, but only when Requesty is
    configured; otherwise it falls back to the extractor gate with a warning so a missing
    key never breaks the stream.
    """
    choice = os.getenv("CLAIM_GATE", "extractor").strip().lower()
    if choice == "jev":
        if JevScorer.is_configured():
            logger.info("Claim gate: JevGate (per-sentence Jev + reformulation)")
            return JevGate(extractor)
        logger.warning("CLAIM_GATE=jev but REQUESTY_API_KEY is unset; using ExtractorGate")
    return ExtractorGate(extractor)
