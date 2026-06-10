"""
Shared PydanticAI model foundation.

One place that wires the Google provider, primary/fallback models, and
default model settings used by every agent in the service layer.
"""

import os

from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.providers.google import GoogleProvider

# Deterministic output across all agents (matches old temperature=0).
MODEL_SETTINGS = GoogleModelSettings(temperature=0)


def _provider() -> GoogleProvider:
    """Build a GoogleProvider from the Gemini/Google API key in the environment."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set")
    return GoogleProvider(api_key=api_key)


def build_model(primary: str, fallback: str | None = None):
    """Return a GoogleModel, or a FallbackModel(primary, fallback) if a fallback is given."""
    provider = _provider()
    primary_model = GoogleModel(primary, provider=provider)
    if fallback:
        return FallbackModel(primary_model, GoogleModel(fallback, provider=provider))
    return primary_model
