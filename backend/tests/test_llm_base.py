"""Tests for the shared PydanticAI model foundation."""

import pytest

from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.fallback import FallbackModel


@pytest.fixture
def no_provider_fallback(monkeypatch):
    """Pin the cross-provider fallback to 'off'.

    backend/app.py calls load_dotenv() at import time, so importing the app pulls the
    developer's real .env into os.environ for the whole session. Without this fixture
    these tests would pass or fail depending on whether the machine running them has
    REQUESTY_API_KEY set — green on a machine with no .env, red on the VPS.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("REQUESTY_API_KEY", raising=False)


def test_build_model_returns_google_model_without_fallback(no_provider_fallback):
    from backend.services.llm_base import build_model

    model = build_model("gemini-2.5-pro")
    assert isinstance(model, GoogleModel)


def test_build_model_returns_fallback_when_fallback_given(no_provider_fallback):
    from backend.services.llm_base import build_model

    model = build_model("gemini-2.5-pro", "gemini-3-flash-preview")
    assert isinstance(model, FallbackModel)


def test_build_model_appends_cross_provider_fallback_when_key_set(monkeypatch):
    """A configured REQUESTY_API_KEY adds the non-Google layer that survives a Google outage."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("REQUESTY_API_KEY", "test-requesty-key")
    from backend.services.llm_base import build_model

    model = build_model("gemini-2.5-pro")
    assert isinstance(model, FallbackModel)


def test_build_model_skips_cross_provider_fallback_when_disabled(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("REQUESTY_API_KEY", "test-requesty-key")
    monkeypatch.setenv("PROVIDER_FALLBACK_ENABLED", "false")
    from backend.services.llm_base import build_model

    model = build_model("gemini-2.5-pro")
    assert isinstance(model, GoogleModel)


def test_build_model_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from backend.services.llm_base import build_model

    with pytest.raises(ValueError, match="GEMINI_API_KEY or GOOGLE_API_KEY"):
        build_model("gemini-2.5-pro")
