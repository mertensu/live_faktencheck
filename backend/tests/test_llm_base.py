"""Tests for the shared PydanticAI model foundation."""

import pytest

from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.fallback import FallbackModel


def test_build_model_returns_google_model_without_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from backend.services.llm_base import build_model

    model = build_model("gemini-2.5-pro")
    assert isinstance(model, GoogleModel)


def test_build_model_returns_fallback_when_fallback_given(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from backend.services.llm_base import build_model

    model = build_model("gemini-2.5-pro", "gemini-3-flash-preview")
    assert isinstance(model, FallbackModel)


def test_build_model_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from backend.services.llm_base import build_model

    with pytest.raises(ValueError, match="GEMINI_API_KEY or GOOGLE_API_KEY"):
        build_model("gemini-2.5-pro")
