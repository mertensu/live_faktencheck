"""
Shared PydanticAI model foundation.

One place that wires the Google provider, primary/fallback models, and
default model settings used by every agent in the service layer.

Fallback layers (in order):
  1. primary GoogleModel
  2. optional secondary GoogleModel (same provider — guards a single overloaded model)
  3. optional cross-provider model via Requesty (OpenAI-compatible), e.g. Claude in the
     EU — guards a full Google outage / quota exhaustion / key failure. Enabled whenever
     REQUESTY_API_KEY is set and PROVIDER_FALLBACK_ENABLED is not "false".
"""

import os

from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

# Deterministic output across all agents (matches old temperature=0).
MODEL_SETTINGS = GoogleModelSettings(temperature=0)


def _provider() -> GoogleProvider:
    """Build a GoogleProvider from the Gemini/Google API key in the environment."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set")
    return GoogleProvider(api_key=api_key)


def _provider_fallback_model() -> OpenAIModel | None:
    """Cross-provider (non-Google) fallback via Requesty's OpenAI-compatible router.

    Returns None when disabled or unconfigured, so a missing key never breaks startup —
    the pipeline simply falls back to Google-only behaviour.
    """
    if os.getenv("PROVIDER_FALLBACK_ENABLED", "true").lower() == "false":
        return None
    api_key = os.getenv("REQUESTY_API_KEY")
    if not api_key:
        return None
    base_url = os.getenv("REQUESTY_BASE_URL", "https://router.requesty.ai/v1")
    model_name = os.getenv("PROVIDER_FALLBACK_MODEL", "claude-opus-4-8@eu")
    provider = OpenAIProvider(base_url=base_url, api_key=api_key)
    return OpenAIModel(model_name, provider=provider)


def build_model(primary: str, fallback: str | None = None):
    """Build the model chain for an agent.

    Returns a bare GoogleModel when only one layer applies, or a FallbackModel that
    tries, in order: primary Google → optional secondary Google → optional cross-provider
    (Requesty/Claude). FallbackModel switches on any ModelAPIError (HTTP 4xx/5xx, rate
    limits, connection failures), so a Google outage or quota wall reaches the last layer.
    """
    provider = _provider()
    models = [GoogleModel(primary, provider=provider)]
    if fallback:
        models.append(GoogleModel(fallback, provider=provider))

    provider_fb = _provider_fallback_model()
    if provider_fb is not None:
        models.append(provider_fb)

    if len(models) == 1:
        return models[0]
    return FallbackModel(*models)
