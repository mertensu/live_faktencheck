"""
Shared PydanticAI model foundation.

One place that wires the Google provider, primary/fallback models, and
default model settings used by every agent in the service layer.

A model name with "@" (e.g. ``gpt-6-luna@eu``, ``vertex/gemini-3.8-flash@eu``) runs via
Requesty's EU router instead of Google directly; its fallback is then a Google model, so a
Requesty outage or a slow call never stalls the live lane.

Fallback layers (in order):
  1. primary model (GoogleModel, or a Requesty model with a short timeout)
  2. optional secondary GoogleModel (always set for a Requesty primary)
  3. optional cross-provider model via Requesty (OpenAI-compatible), e.g. Claude in the
     EU — guards a full Google outage / quota exhaustion / key failure. Enabled whenever
     REQUESTY_API_KEY is set and PROVIDER_FALLBACK_ENABLED is not "false".
"""

import logging
import os

from openai import AsyncOpenAI
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings, OpenAIModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider

logger = logging.getLogger(__name__)

# Google fallback behind a Requesty primary.
GOOGLE_FALLBACK_MODEL = "gemini-3.6-flash"

# Deterministic output across all agents (matches old temperature=0).
MODEL_SETTINGS = GoogleModelSettings(temperature=0)


def settings_with_thinking(level: str | None) -> GoogleModelSettings:
    """``MODEL_SETTINGS`` plus a Gemini thinking level ("minimal"/"low"/"medium"/"high").

    Empty/None keeps the model's default. Latency lever for the live lane: thinking
    dominates the call time of the flash models. Non-Google fallback layers ignore it.
    """
    level = (level or "").strip().lower()
    if not level:
        return MODEL_SETTINGS
    return GoogleModelSettings(temperature=0, google_thinking_config={"thinking_level": level})


def _provider() -> GoogleProvider:
    """Build a GoogleProvider from the Gemini/Google API key in the environment."""
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set")
    return GoogleProvider(api_key=api_key)


def _requesty_provider(timeout: float | None = None) -> OpenAIProvider:
    client = AsyncOpenAI(
        base_url=os.getenv("REQUESTY_BASE_URL", "https://router.requesty.ai/v1"),
        api_key=os.getenv("REQUESTY_API_KEY"),
        # A timed-out primary falls through to Google; retries would only add to the wait.
        **({"timeout": timeout, "max_retries": 0} if timeout else {}),
    )
    return OpenAIProvider(openai_client=client)


def is_requesty_model(name: str | None) -> bool:
    """Model names with a Requesty region suffix ("@eu") go through Requesty."""
    return "@" in (name or "")


def _requesty_model(name: str, thinking: str | None) -> OpenAIChatModel:
    """A live-lane model via Requesty. The thinking level becomes the reasoning effort; it
    sits on the model so the Google layers behind it keep their own thinking config. The
    per-call timeout caps rare router stalls (~28 s seen in benchmarks) before falling back."""
    level = (thinking or "").strip().lower()
    settings = OpenAIChatModelSettings(openai_reasoning_effort=level) if level else None
    timeout = float(os.getenv("REQUESTY_TIMEOUT_S", "12"))
    return OpenAIChatModel(name, provider=_requesty_provider(timeout), settings=settings)


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
    model_name = os.getenv("PROVIDER_FALLBACK_MODEL", "claude-opus-4-8@eu")
    return OpenAIModel(model_name, provider=_requesty_provider())


def build_model(primary: str, fallback: str | None = None, thinking: str | None = None):
    """Build the model chain for an agent.

    Returns a bare GoogleModel when only one layer applies, or a FallbackModel that
    tries, in order: primary Google → optional secondary Google → optional cross-provider
    (Requesty/Claude). FallbackModel switches on any ModelAPIError (HTTP 4xx/5xx, rate
    limits, connection failures), so a Google outage or quota wall reaches the last layer.

    A Requesty primary (name with "@") is followed by ``fallback`` or
    ``GOOGLE_FALLBACK_MODEL``; ``thinking`` sets its reasoning effort. Without
    REQUESTY_API_KEY it is skipped and the Google fallback becomes the primary.
    """
    provider = _provider()
    models = []
    if is_requesty_model(primary):
        if os.getenv("REQUESTY_API_KEY"):
            models.append(_requesty_model(primary, thinking))
        else:
            logger.warning("REQUESTY_API_KEY not set — %s runs on Google instead", primary)
        fallback = fallback or os.getenv("GOOGLE_FALLBACK_MODEL", GOOGLE_FALLBACK_MODEL)
    else:
        models.append(GoogleModel(primary, provider=provider))
    if fallback:
        models.append(GoogleModel(fallback, provider=provider))

    provider_fb = _provider_fallback_model()
    if provider_fb is not None:
        models.append(provider_fb)

    if len(models) == 1:
        return models[0]
    return FallbackModel(*models)
