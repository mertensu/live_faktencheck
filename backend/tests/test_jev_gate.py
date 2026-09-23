"""
Tests for the Jev per-sentence claim gate (JevGate) and its wiring.

Covered:
- JevGate satisfies the ClaimGate protocol.
- A window is split per sentence; only sentences scoring >= CHECK_HI are reformulated
  into claims, and the grey zone / misses are skipped.
- Reformulation only runs on hits (the scorer, not the LLM, decides check-worthiness).
- Speaker prefixes are parsed and excluded_speakers are dropped before scoring.
- An empty / whitespace window short-circuits without scoring.
- build_gate() picks JevGate only when CLAIM_GATE=jev and Requesty is configured,
  otherwise falls back to ExtractorGate.
"""

from unittest.mock import patch

from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from backend.services.claim_extraction import ClaimExtractor, ExtractedClaim, ReformulatedClaim
from backend.services.gate import (
    ClaimGate,
    ExtractorGate,
    JevGate,
    JevScore,
    JevScorer,
    build_gate,
)

models.ALLOW_MODEL_REQUESTS = False


def _make_extractor():
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-api-key"}):
        return ClaimExtractor()


class FakeScorer:
    """A JevScorer stub returning canned check/importance probs per sentence text."""

    def __init__(self, scores: dict[str, float], default: float = 0.0,
                 importance: dict[str, float] | None = None, default_importance: float = 1.0):
        self._scores = scores
        self._default = default
        self._importance = importance or {}
        self._default_importance = default_importance
        self.calls: list[str] = []

    async def score(self, sentence: str) -> JevScore:
        self.calls.append(sentence)
        check = next((v for k, v in self._scores.items() if k in sentence), self._default)
        imp = next((v for k, v in self._importance.items() if k in sentence), self._default_importance)
        return JevScore(check=check, important=imp)


class TestJevGate:
    async def test_is_claim_gate(self):
        gate = JevGate(_make_extractor(), FakeScorer({}))
        assert isinstance(gate, ClaimGate)

    async def test_only_hits_are_reformulated(self):
        ex = _make_extractor()
        scorer = FakeScorer({"NATO": 0.97, "zu hoch": 0.10, "zu wenig": 0.55})
        gate = JevGate(ex, scorer)
        window = (
            "Anna: Deutschland ist Mitglied der NATO. "
            "Die Steuern sind zu hoch. "
            "In Deutschland wird zu wenig gearbeitet."
        )
        # Reformulator echoes a standalone claim for whatever sentence reaches it.
        reformulated = ExtractedClaim(name="Anna", claim="Deutschland ist Mitglied der NATO.")
        with ex.reformulator.override(model=TestModel(custom_output_args=reformulated.model_dump())):
            out = await gate.gate(window, guests=["Anna"])
        # 3 sentences scored, only the NATO one (>=0.85) becomes a claim.
        assert len(scorer.calls) == 3
        assert len(out) == 1
        assert out[0].claim == "Deutschland ist Mitglied der NATO."
        # The original transcript sentence is preserved as the UI highlight anchor,
        # even though `claim` is the reformulated text.
        assert out[0].source == "Deutschland ist Mitglied der NATO."

    async def test_search_queries_pass_through(self):
        ex = _make_extractor()
        gate = JevGate(ex, FakeScorer({"NATO": 0.97}))
        reformulated = ReformulatedClaim(
            name="Anna", claim="Deutschland ist Mitglied der NATO.",
            search_queries=["NATO Mitgliedstaaten", "Deutschland NATO Beitritt 1955"],
        )
        with ex.reformulator.override(model=TestModel(custom_output_args=reformulated.model_dump())):
            out = await gate.gate("Anna: Deutschland ist Mitglied der NATO.", guests=["Anna"])
        assert out[0].search_queries == ["NATO Mitgliedstaaten", "Deutschland NATO Beitritt 1955"]

    async def test_unimportant_hit_is_dropped_before_llm(self):
        """A checkable-but-trivial sentence scores high on Jev's check question but low on
        importance, so it is dropped before the reformulator LLM ever runs."""
        ex = _make_extractor()
        scorer = FakeScorer({"vorgestellt": 0.91}, importance={"vorgestellt": 0.20})
        gate = JevGate(ex, scorer)
        # No reformulator override + ALLOW_MODEL_REQUESTS=False => an LLM call would raise.
        out = await gate.gate("A: Am Montag hat sie das Monitoring vorgestellt.", guests=[])
        assert out == []
        assert scorer.calls == ["Am Montag hat sie das Monitoring vorgestellt."]

    async def test_no_hits_yields_empty_without_llm(self):
        ex = _make_extractor()
        scorer = FakeScorer({}, default=0.2)  # everything below threshold
        gate = JevGate(ex, scorer)
        # No reformulator override + ALLOW_MODEL_REQUESTS=False => any LLM call would raise.
        out = await gate.gate("Guten Abend, schön dass Sie da sind. Wie geht es Ihnen?", guests=[])
        assert out == []
        assert len(scorer.calls) == 2  # both sentences were scored

    async def test_grey_zone_is_skipped(self):
        ex = _make_extractor()
        scorer = FakeScorer({"innovativste": 0.63})  # grey zone (0.30..0.85)
        gate = JevGate(ex, scorer)
        out = await gate.gate("Deutschland ist das innovativste Land Europas.", guests=[])
        assert out == []

    async def test_excluded_speaker_is_dropped_before_scoring(self):
        ex = _make_extractor()
        scorer = FakeScorer({"NATO": 0.97})
        gate = JevGate(ex, scorer)
        window = "Moderator: Deutschland ist Mitglied der NATO."
        out = await gate.gate(window, guests=[], excluded_speakers=["Moderator"])
        assert out == []
        assert scorer.calls == []  # never scored — dropped by speaker

    async def test_empty_window_skips_scoring(self):
        gate = JevGate(_make_extractor(), FakeScorer({"x": 0.99}))
        assert await gate.gate("   ", guests=[]) == []


class TestBuildGate:
    def test_default_is_extractor_gate(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("CLAIM_GATE", None)
            gate = build_gate(_make_extractor())
        assert isinstance(gate, ExtractorGate)

    def test_jev_selected_when_configured(self):
        with patch.dict("os.environ", {"CLAIM_GATE": "jev", "REQUESTY_API_KEY": "k"}):
            gate = build_gate(_make_extractor())
        assert isinstance(gate, JevGate)

    def test_jev_falls_back_without_key(self):
        env = {"CLAIM_GATE": "jev"}
        with patch.dict("os.environ", env, clear=False):
            import os
            os.environ.pop("REQUESTY_API_KEY", None)
            gate = build_gate(_make_extractor())
        assert isinstance(gate, ExtractorGate)


class TestJevScorer:
    def test_is_configured_reflects_key(self):
        with patch.dict("os.environ", {"REQUESTY_API_KEY": "k"}):
            assert JevScorer.is_configured() is True
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("REQUESTY_API_KEY", None)
            assert JevScorer.is_configured() is False
