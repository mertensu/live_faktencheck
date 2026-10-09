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
from dataclasses import dataclass, field
from typing import List, Protocol, runtime_checkable

from backend.utils import log_text

from .claim_extraction import ExtractedClaim, ClaimExtractor

logger = logging.getLogger(__name__)


@dataclass
class GatedClaim:
    """A gated claim plus the *original* transcript sentence it was extracted from.

    ``JevGate`` returns these instead of bare ``ExtractedClaim`` so the streaming layer
    can tell the UI which passage to highlight (``claim`` is the reformulated text, which
    no longer matches the transcript). Duck-compatible with ``ExtractedClaim`` for the
    ``.name``/``.claim`` access the streaming layer does; ``.source`` is the extra.
    """
    name: str
    claim: str
    source: str
    search_queries: list[str] = field(default_factory=list)


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
        speaker_names: dict[str, str] | None = None,
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
        speaker_names: dict[str, str] | None = None,  # unused: the window agent names speakers itself
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

# Jev answers TWO yes/no ("noul") questions in a single per-sentence call: is the sentence
# checkable, and is it important enough to check on air. The sentence is the "state"
# (message content); Jev returns a calibrated probability per question. Two questions in
# one call means the importance judgment costs no extra round-trip.
_JEV_QUESTIONS = {
    "claim": {
        "type": "noul",
        "instructions": "Enthält dieser Satz eine überprüfbare Tatsachenbehauptung, die man faktenchecken könnte?",
        "criteria": {
            "true": "Überprüfbarer Tatsachenkern: Zahl, Statistik, Datum, historisches oder aktuelles Faktum, konkrete Aussage über die Realität (wer/was/wann).",
            "false": "Reine Meinung, Wertung, Absicht, Forderung, Frage, Begrüßung oder Floskel ohne überprüfbaren Tatsachenkern.",
        },
    },
    "important": {
        "type": "noul",
        "instructions": "Ist diese Behauptung inhaltlich bedeutsam bzw. interessant genug, um sie in einer Live-Sendung zu faktenchecken?",
        "criteria": {
            "true": "Inhaltlich bedeutsame, strittige oder überraschende Tatsachenbehauptung, die eine Debatte trägt (Zahl, Statistik, Kausalbehauptung, historisches/aktuelles Faktum).",
            "false": "Belanglos oder prozedural: reine Termin-/Ablaufankündigung (z. B. 'am Montag wurde X vorgestellt'), Trivialität, Selbstverständlichkeit oder Randnotiz ohne Aussagekraft.",
        },
    },
}


@dataclass
class JevScore:
    """Jev's two per-sentence probabilities (either may be ``None`` on a parse/call error)."""
    check: float | None       # is it a checkable factual claim?
    important: float | None    # is it worth checking on air?


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

    ``score`` returns a ``JevScore`` with the checkable and importance probabilities in
    [0, 1] (each ``None`` if the call fails or the answer can't be parsed). The client is
    built lazily so importing this module never requires a key or network.
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

            # Jev answers in well under a second. Without a short timeout one stalled call
            # (seen live: minutes) holds its whole window, since the gate awaits every
            # sentence of it; a timed-out call is retried once, then treated as skip.
            self._client = AsyncOpenAI(
                api_key=os.getenv("REQUESTY_API_KEY"),
                base_url=os.getenv("REQUESTY_BASE_URL", "https://router.requesty.ai/v1"),
                timeout=float(os.getenv("JEV_TIMEOUT_S", "5")),
                max_retries=1,
            )
        return self._client

    async def score(self, sentence: str) -> JevScore:
        try:
            resp = await self._get_client().chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": sentence}],
                response_format={"type": "questions", "questions": _JEV_QUESTIONS},
            )
            data = json.loads(resp.choices[0].message.content or "")
            return JevScore(
                check=_extract_prob(data.get("claim")),
                important=_extract_prob(data.get("important")),
            )
        except Exception:
            logger.exception("Jev scoring failed for sentence; treating as skip")
            return JevScore(None, None)


# --- Jev gate ----------------------------------------------------------------

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


# Window-line prefix for a line without a speaker label.
NO_SPEAKER = "?"


def _split_speaker(line: str) -> tuple[str, str]:
    """Split a ``"Speaker: text"`` window line into (speaker, text).

    The streaming layer prefixes every line with ``"{label}: "``, and a line without a
    speaker with ``"?: "`` — otherwise a colon in the text ("… gesagt: Ja …") would read
    as a speaker. If no prefix is present, the whole line is text with an empty speaker.
    """
    m = re.match(r"^\s*([^:\n]{1,60}?):\s+(.*)$", line, re.DOTALL)
    if m:
        speaker = m.group(1).strip()
        return ("" if speaker == NO_SPEAKER else speaker), m.group(2).strip()
    return "", line.strip()


class JevGate:
    """``ClaimGate`` that gates per sentence with Jev, then reformulates the hits.

    Pipeline per window:
      1. Split the window into (speaker, sentence) pairs.
      2. Score every sentence with Jev, concurrently. A hit needs ``check >= CHECK_HI``
         and ``important >= IMPORTANCE``.
      3. A sentence in the grey zone (not a hit, but check and importance above the grey
         thresholds) gets a second opinion from a fast LLM; a yes makes it a hit.
      4. For each hit, an LLM call reformulates the sentence into a standalone claim
         (pronouns resolved from rolling context, speaker assigned) and writes search
         queries for the fast checker. Check-worthiness is decided by then — this step
         does not re-judge it.
    """

    def __init__(self, extractor: ClaimExtractor, scorer: JevScorer | None = None):
        self._extractor = extractor
        self._scorer = scorer or JevScorer()
        self.check_hi = float(os.getenv("JEV_CHECK_THRESHOLD", "0.80"))
        # Below this check prob a sentence is skipped outright; between it and check_hi lies
        # the grey zone.
        self.skip_lo = float(os.getenv("JEV_SKIP_THRESHOLD", "0.40"))
        # A checkable sentence still needs this importance prob to be worth checking on air
        # (filters trivial/procedural facts). Fail-open: a missing importance score never
        # drops an otherwise-good claim.
        self.imp_hi = float(os.getenv("JEV_IMPORTANCE_THRESHOLD", "0.60"))
        # Opt-in per-sentence trace (sentence, p, band) — for reviewing a live run, since
        # the DB keeps only the claims that passed, not scores or skipped sentences.
        self._debug = os.getenv("JEV_GATE_DEBUG", "").strip().lower() in ("1", "true", "yes")
        # Grey zone: neither a clear hit nor clearly nothing. Talk-show claims are often
        # wrapped in an assessment ("Der Staat gibt immer mehr Geld aus" scored 0.82 check
        # but 0.54 importance; "Steuererhöhungen führen zu keinem Wachstum" 0.49 check), so
        # a sentence with check >= JEV_SKIP_THRESHOLD and importance >=
        # JEV_GREY_IMPORTANCE_THRESHOLD that is not a hit goes to a fast LLM for a second
        # opinion; only on yes is it reformulated and checked.
        self.grey_zone = os.getenv("JEV_GREY_ZONE", "true").strip().lower() in ("1", "true", "yes")
        self.grey_imp = float(os.getenv("JEV_GREY_IMPORTANCE_THRESHOLD", "0.40"))
        # How many preceding sentences the reformulator sees to resolve "er", "das", …
        self.context_sentences = int(os.getenv("REFORMULATE_CONTEXT_SENTENCES", "4"))

    def _verdict(self, sc: JevScore) -> str:
        """``CHECK`` (a hit), ``grey`` (ask the second opinion), or why it is skipped."""
        if sc.check is None:
            return "err"
        # A missing importance score never drops an otherwise-good claim (fail-open).
        imp = 1.0 if sc.important is None else sc.important
        if sc.check >= self.check_hi and imp >= self.imp_hi:
            return "CHECK"
        if self.grey_zone and sc.check >= self.skip_lo and imp >= self.grey_imp:
            return "grey"
        if sc.check >= self.check_hi:
            return "unwichtig"
        return "skip"

    async def _second_opinion(self, sentence: str, speaker: str, context: str,
                              previous_context: str | None) -> str:
        """Ask the grey-zone judge; ``CHECK`` on yes. A failed call skips the sentence."""
        try:
            yes = await self._extractor.judge_grey_zone_async(
                sentence, speaker=speaker, context=context, previous_context=previous_context)
        except Exception:
            logger.exception("Grey-zone judge failed; skipping sentence")
            return "err"
        if self._debug:
            logger.info(f"JevGate[grey -> {'CHECK' if yes else 'skip'}] {log_text(sentence)}")
        return "CHECK" if yes else "grey-no"

    async def gate(
        self,
        window_text: str,
        guests: list[str],
        context: str = "",
        conversation_type: str = "",
        excluded_speakers: list[str] | None = None,
        previous_context: str | None = None,
        speaker_names: dict[str, str] | None = None,
    ) -> List[GatedClaim]:
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
            for sentence in split_sentences(text):
                pairs.append((speaker, sentence))

        if not pairs:
            return []

        scores = await asyncio.gather(*(self._scorer.score(s) for _, s in pairs))

        # The reformulator resolves pronouns from the last few sentences before the one it
        # rewrites, with speakers by name (the operator's assignment) instead of labels.
        names = speaker_names or {}

        def line(speaker: str, sentence: str) -> str:
            return f"{names.get(speaker, speaker)}: {sentence}" if speaker else sentence

        # Every sentence (hit or not) extends the rolling context for the ones after it.
        rolling = [ln for ln in (previous_context or "").splitlines() if ln.strip()]
        lines = rolling + [line(spk, sent) for spk, sent in pairs]

        def context_before(i: int) -> str | None:
            end = len(rolling) + i
            return "\n".join(lines[max(0, end - self.context_sentences):end]) or None

        async def handle(i: int) -> GatedClaim | None:
            (speaker, sentence), sc = pairs[i], scores[i]
            verdict = self._verdict(sc)
            if self._debug:
                c_str = "  ? " if sc.check is None else f"{sc.check:.2f}"
                i_str = " ? " if sc.important is None else f"{sc.important:.2f}"
                logger.info(f"JevGate[{verdict:7} p={c_str} imp={i_str}] {speaker or '—'}: {log_text(sentence)}")
            if verdict == "grey":
                verdict = await self._second_opinion(sentence, names.get(speaker, speaker), context, context_before(i))
            if verdict != "CHECK":
                return None
            try:
                claim = await self._extractor.reformulate_claim_async(
                    sentence,
                    speaker=names.get(speaker, speaker),
                    guests=guests,
                    context=context,
                    previous_context=context_before(i),
                )
            except Exception:
                logger.exception("Reformulation failed for gated sentence")
                return None
            if not claim or not (claim.claim or "").strip():
                return None
            # Keep the original sentence as the highlight anchor for the UI.
            return GatedClaim(
                name=claim.name or names.get(speaker, speaker), claim=claim.claim, source=sentence,
                search_queries=list(getattr(claim, "search_queries", None) or []),
            )

        # Hits are reformulated and grey sentences judged concurrently; claims keep the
        # order of their sentences.
        results = await asyncio.gather(*(handle(i) for i in range(len(pairs))))
        claims: List[GatedClaim] = [c for c in results if c is not None]

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
