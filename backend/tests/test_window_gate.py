"""
Tests for the live window gate (SG-2).

Covered:
- extract_window_async returns claims for a claim-bearing window
- an empty / whitespace window short-circuits to [] without calling the model
- ExtractorGate satisfies the ClaimGate protocol and delegates to the extractor
"""

from unittest.mock import patch

from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from backend.services.claim_extraction import ClaimExtractor, ExtractedClaim, ClaimList
from backend.services.gate import ClaimGate, ExtractorGate

models.ALLOW_MODEL_REQUESTS = False


CLAIMS = ClaimList(claims=[ExtractedClaim(name="Julia Berger", claim="Deutschland hat 83 Mio. Einwohner.")])
NO_CLAIMS = ClaimList(claims=[])


def _make_extractor():
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-api-key"}):
        return ClaimExtractor()


class TestWindowGate:
    async def test_window_with_claim_yields_claims(self):
        ex = _make_extractor()
        with ex.window_gate.override(model=TestModel(custom_output_args=CLAIMS.model_dump())):
            out = await ex.extract_window_async(
                "Julia Berger: Deutschland hat 83 Millionen Einwohner.", guests=["Julia Berger"]
            )
        assert len(out) == 1
        assert out[0].name == "Julia Berger"

    async def test_chatty_window_yields_empty(self):
        ex = _make_extractor()
        with ex.window_gate.override(model=TestModel(custom_output_args=NO_CLAIMS.model_dump())):
            out = await ex.extract_window_async("Guten Abend, schön dass Sie da sind.", guests=[])
        assert out == []

    async def test_empty_window_skips_model(self):
        """A blank window must not spend a model call."""
        ex = _make_extractor()
        # No override + ALLOW_MODEL_REQUESTS=False => any real call would raise.
        assert await ex.extract_window_async("   ", guests=[]) == []
        assert await ex.extract_window_async("", guests=[]) == []

    async def test_extractor_gate_delegates(self):
        ex = _make_extractor()
        gate = ExtractorGate(ex)
        assert isinstance(gate, ClaimGate)
        with ex.window_gate.override(model=TestModel(custom_output_args=CLAIMS.model_dump())):
            out = await gate.gate("Julia Berger: 83 Millionen Einwohner.", guests=["Julia Berger"])
        assert len(out) == 1
