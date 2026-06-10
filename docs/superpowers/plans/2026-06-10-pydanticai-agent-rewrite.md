# PydanticAI + Logfire Agent Rewrite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the entire LLM layer (speaker resolution, claim extraction, fact-check agent, self-critique) from LangChain/LangGraph + raw `google-genai` onto a single PydanticAI foundation with optional Logfire observability, keeping all service-level public APIs and behavior identical.

**Architecture:** A shared `llm_base.build_model()` produces a `GoogleModel` (+ `FallbackModel`). Each LLM step becomes a PydanticAI `Agent` with a typed `output_type`; only the fact-checker has a tool (`tavily_search`) and therefore loops. Logfire is wired once at startup and is a silent no-op without a token. `CostTracker`, `studio_graph`, and `mock_search` are deleted; their roles move to Logfire and PydanticAI's test models.

**Tech Stack:** PydanticAI (`pydantic-ai`), Logfire (`logfire`), `tavily-python`, `google-genai` (still used elsewhere), Gemini 2.5/3 models, pytest.

**Spec:** `docs/superpowers/specs/2026-06-10-pydanticai-agent-rewrite-design.md`

**Working dir:** all commands run from the worktree root `/Users/ulfmertens/Documents/fact_check/.claude/worktrees/session-multitenancy`. Use `uv run` for Python.

---

## Task 1: Swap dependencies

**Files:**
- Modify: `pyproject.toml` (dependencies array)

- [ ] **Step 1: Remove LangChain/LangGraph deps and add PydanticAI + Logfire**

In `pyproject.toml`, delete these dependency lines:
```toml
    # LangChain / LangGraph
    "langchain>=1.2.8",
    "langchain-google-genai>=4.2.0",
    "langchain-tavily>=0.2.16",
    "langgraph>=1.0.6",
    "langgraph-cli[inmem]>=0.4.12",
```
And add (keep `google-genai` and `tavily-python` lines as they are):
```toml
    "pydantic-ai>=1.0.0",
    "logfire>=3.0.0",
```

- [ ] **Step 2: Sync the environment**

Run: `uv sync`
Expected: resolves and installs `pydantic-ai` + `logfire`, removes langchain/langgraph packages. Exit code 0.

- [ ] **Step 3: Verify imports resolve**

Run:
```bash
uv run python -c "import pydantic_ai, logfire; from pydantic_ai.models.google import GoogleModel, GoogleModelSettings; from pydantic_ai.models.fallback import FallbackModel; from pydantic_ai.providers.google import GoogleProvider; from pydantic_ai.models.test import TestModel; from pydantic_ai.models.function import FunctionModel; from pydantic_ai import Agent, UsageLimits, UsageLimitExceeded; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "Phase R: swap langchain/langgraph deps for pydantic-ai + logfire"
```

---

## Task 2: Shared model foundation (`llm_base.py`)

**Files:**
- Create: `backend/services/llm_base.py`
- Test: `backend/tests/test_llm_base.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_llm_base.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.services.llm_base'`.

- [ ] **Step 3: Write the implementation**

Create `backend/services/llm_base.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/test_llm_base.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/llm_base.py backend/tests/test_llm_base.py
git commit -m "Phase R: add shared PydanticAI model foundation (llm_base)"
```

---

## Task 3: Tavily search tool (`search.py`)

**Files:**
- Create: `backend/services/search.py`
- Test: `backend/tests/test_search.py`

This is the PydanticAI replacement for `FallbackSearchTool`. The tool function's signature + docstring become the schema exposed to the model. The "empty result with a date filter → retry without it" behavior is preserved inside the function.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the tavily_search PydanticAI tool."""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_tavily(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    # Reset the cached client so each test gets a fresh mock.
    import backend.services.search as search_mod
    search_mod._client = None
    with patch("backend.services.search.AsyncTavilyClient") as cls:
        instance = cls.return_value
        instance.search = AsyncMock()
        yield instance


async def test_search_returns_results(mock_tavily):
    from backend.services.search import tavily_search
    mock_tavily.search.return_value = {"results": [{"title": "t", "url": "u"}]}

    result = await tavily_search("Mindestlohn 2024")

    assert result["results"][0]["url"] == "u"
    mock_tavily.search.assert_awaited_once()


async def test_search_retries_without_date_filter_on_empty(mock_tavily):
    from backend.services.search import tavily_search
    # First call (with date filter) empty, second call (no filter) has results.
    mock_tavily.search.side_effect = [
        {"results": []},
        {"results": [{"title": "t", "url": "u"}]},
    ]

    result = await tavily_search("Mindestlohn", start_date="2024-01-01")

    assert result["results"][0]["url"] == "u"
    assert mock_tavily.search.await_count == 2
    # Second call must NOT carry the date filter.
    second_kwargs = mock_tavily.search.await_args_list[1].kwargs
    assert "start_date" not in second_kwargs


async def test_search_no_retry_when_no_date_filter(mock_tavily):
    from backend.services.search import tavily_search
    mock_tavily.search.return_value = {"results": []}

    result = await tavily_search("Mindestlohn")

    assert result["results"] == []
    assert mock_tavily.search.await_count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_search.py -v`
Expected: FAIL — `No module named 'backend.services.search'`.

- [ ] **Step 3: Write the implementation**

Create `backend/services/search.py`:
```python
"""
Web search tool for the fact-check agent.

Wraps tavily-python directly (PydanticAI tool). Restricts results to trusted
German domains and retries without the date filter when a date-filtered search
returns nothing — the behavior previously provided by FallbackSearchTool.
"""

import os
import logging

from tavily import AsyncTavilyClient

from .trusted_domains import TRUSTED_DOMAINS

logger = logging.getLogger(__name__)

_client: AsyncTavilyClient | None = None


def _get_client() -> AsyncTavilyClient:
    global _client
    if _client is None:
        api_key = os.getenv("TAVILY_API_KEY")
        if not api_key:
            raise ValueError("TAVILY_API_KEY environment variable not set")
        _client = AsyncTavilyClient(api_key=api_key)
    return _client


async def tavily_search(
    query: str,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """Search the web to verify a claim against trusted German sources.

    Args:
        query: The search query, in German.
        start_date: Optional earliest publication date, format YYYY-MM-DD.
        end_date: Optional latest publication date, format YYYY-MM-DD.
    """
    client = _get_client()
    kwargs: dict = {
        "search_depth": os.getenv("TAVILY_SEARCH_DEPTH", "basic"),
        "max_results": int(os.getenv("TAVILY_MAX_RESULTS", "5")),
        "include_domains": TRUSTED_DOMAINS,
    }
    if start_date:
        kwargs["start_date"] = start_date
    if end_date:
        kwargs["end_date"] = end_date

    result = await client.search(query, **kwargs)

    if not result.get("results") and (start_date or end_date):
        logger.info("Empty results with date filter — retrying without date filter: '%s'", query)
        kwargs.pop("start_date", None)
        kwargs.pop("end_date", None)
        result = await client.search(query, **kwargs)

    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/test_search.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/search.py backend/tests/test_search.py
git commit -m "Phase R: add tavily_search PydanticAI tool with date-filter fallback"
```

---

## Task 4: Logfire wiring (`observability.py`)

**Files:**
- Create: `backend/services/observability.py`
- Test: `backend/tests/test_observability.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for Logfire configuration."""

from unittest.mock import patch


def test_configure_logfire_is_idempotent_and_calls_logfire():
    import backend.services.observability as obs
    obs._configured = False

    with patch("logfire.configure") as cfg, patch("logfire.instrument_pydantic_ai") as instr:
        obs.configure_logfire()
        obs.configure_logfire()  # second call is a no-op

    cfg.assert_called_once()
    instr.assert_called_once()
    # send_to_logfire must be 'if-token-present' so it is silent without a token.
    assert cfg.call_args.kwargs.get("send_to_logfire") == "if-token-present"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_observability.py -v`
Expected: FAIL — `No module named 'backend.services.observability'`.

- [ ] **Step 3: Write the implementation**

Create `backend/services/observability.py`:
```python
"""
Logfire observability wiring.

Configured once at app startup. With send_to_logfire='if-token-present' it is a
silent no-op when no LOGFIRE_TOKEN is set, so it never becomes a hard runtime
dependency (e.g. on the VPS without a Logfire account).
"""

import logging

logger = logging.getLogger(__name__)

_configured = False


def configure_logfire() -> None:
    """Configure Logfire + PydanticAI instrumentation. Idempotent; safe without a token."""
    global _configured
    if _configured:
        return
    try:
        import logfire
    except ImportError:
        logger.warning("logfire not installed; observability disabled")
        _configured = True
        return

    logfire.configure(send_to_logfire="if-token-present", service_name="fact-check")
    logfire.instrument_pydantic_ai()
    _configured = True
    logger.info("Logfire configured (sends only when LOGFIRE_TOKEN is present)")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/test_observability.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/observability.py backend/tests/test_observability.py
git commit -m "Phase R: add opt-in Logfire observability wiring"
```

---

## Task 5: Rewrite `claim_extraction.py` onto PydanticAI

**Files:**
- Modify (rewrite body): `backend/services/claim_extraction.py`
- Modify: `backend/tests/conftest.py` (replace `mock_genai_client` / `mock_claim_extractor`)
- Modify: `backend/tests/test_claim_extraction.py` (adapt assertions)

Keep the module's public surface unchanged: `resolve_labels_async`, `extract_claims_async`, `extract_async`, `extract` (sync), `select_async`, and all Pydantic models (`ExtractedClaim`, `ClaimList`, `SpeakerLabelMapping`, `ResolvedTranscript`, `SpeakerLabelsInput`, `ClaimExtractionInput`). Three agents: `speaker_resolver`, `claim_extractor`, `selection_agent`. The selection agent templates `{max_claims}` per run via deps. The first-prompt dump files are removed (Logfire replaces them).

- [ ] **Step 1: Replace the conftest fixtures (write the new test scaffolding first)**

In `backend/tests/conftest.py`:

Add these imports near the top (with the other pydantic_ai-free imports):
```python
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

models.ALLOW_MODEL_REQUESTS = False  # fail loudly if a test ever hits a real model
```

Replace the `mock_gemini_response`, `mock_genai_client`, and `mock_claim_extractor` fixtures with:
```python
@pytest.fixture
def mock_gemini_response():
    """Default extracted claims used by the claim_extractor override."""
    return ClaimList(claims=[
        ExtractedClaim(name="Test Speaker", claim="Test claim statement"),
        ExtractedClaim(name="Another Speaker", claim="Another test claim"),
    ])


@pytest.fixture
def mock_claim_extractor(mock_gemini_response):
    """ClaimExtractor with all agents overridden by TestModel (no network)."""
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-api-key"}):
        from backend.services.claim_extraction import ClaimExtractor
        extractor = ClaimExtractor()

    claims_model = TestModel(custom_output_args=mock_gemini_response.model_dump())
    with extractor.claim_extractor.override(model=claims_model), \
         extractor.selection_agent.override(model=claims_model):
        yield extractor
```

Note: `mock_claim_extractor` no longer disables speaker labels by setting `speaker_labels_prompt_template = None`. Tests that exercised extraction without speaker resolution call `extract_claims_async` (which skips resolution by contract). A test that needs speaker resolution overrides `extractor.speaker_resolver` itself (see Step 5 example).

Also update `mock_all_services` to drop `mock_genai_client`/`mock_create_agent` (those are removed in Tasks 5–6); it will be rebuilt in Task 6. For now, change it to:
```python
@pytest.fixture
def mock_all_services(mock_claim_extractor, mock_fact_checker):
    """Provide both mocked services for API-level tests."""
    return {"claim_extractor": mock_claim_extractor, "fact_checker": mock_fact_checker}
```

- [ ] **Step 2: Run the extraction tests to verify they fail**

Run: `uv run pytest backend/tests/test_claim_extraction.py -v`
Expected: FAIL — `ClaimExtractor` has no attribute `claim_extractor` / `selection_agent` yet.

- [ ] **Step 3: Rewrite `claim_extraction.py`**

Replace the entire file with:
```python
"""
Claim Extraction Service using PydanticAI + Gemini.

Two single-shot typed agents: speaker label resolution and claim extraction,
plus a selection agent for autopilot mode. No tools, no loop.
"""

import os
import json
import asyncio
import logging
from dataclasses import dataclass
from typing import List

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from backend.utils import load_prompt
from backend.lang import CLAIM_NAME_DESCRIPTION, CLAIM_TEXT_DESCRIPTION
from .llm_base import build_model, MODEL_SETTINGS

logger = logging.getLogger(__name__)

# Default model if not specified in environment
DEFAULT_MODEL = "gemini-2.5-flash"


class ExtractedClaim(BaseModel):
    """A standalone, decontextualized factual claim."""
    name: str = Field(description=CLAIM_NAME_DESCRIPTION)
    claim: str = Field(description=CLAIM_TEXT_DESCRIPTION)


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
    guests: list[str] = Field(description="Teilnehmer der Sendung, z. B. ['Caren Miosga (Moderatorin)', 'Heidi Reichinnek (Linke)']")
    transcript: str = Field(description="Transkript mit generischen Sprecherbezeichnungen")


class ClaimExtractionInput(BaseModel):
    """Input for claim extraction from a transcript."""
    date: str = Field(description="Sendedatum, z. B. 'Oktober 2025'")
    guests: list[str] = Field(description="Teilnehmer der Sendung")
    context: str = Field(default="", description="Thematischer Hintergrund der Sendung")
    transcript: str = Field(description="Transkript zur Analyse")
    previous_block_ending: str | None = Field(default=None, description="Letzte Zeilen des vorherigen Transkriptblocks zur Gewährleistung der Kontinuität")


@dataclass
class SelectionDeps:
    """Runtime dependency for the selection agent — templates {max_claims}."""
    max_claims: int


class ClaimExtractor:
    """Extracts verifiable claims from transcripts using PydanticAI + Gemini."""

    def __init__(self):
        self.model_name = os.getenv("GEMINI_MODEL_CLAIM_EXTRACTION", DEFAULT_MODEL)
        model = build_model(self.model_name)

        # Bake the input schema into each prompt (placeholder {input_schema}).
        prompt = load_prompt("claim_extraction.md")
        extraction_schema = json.dumps(ClaimExtractionInput.model_json_schema(), indent=2, ensure_ascii=False)
        self.claim_extractor = Agent(
            model,
            output_type=ClaimList,
            instructions=prompt.replace("{input_schema}", extraction_schema),
            model_settings=MODEL_SETTINGS,
        )

        # Selection agent: same ClaimList schema, different prompt, {max_claims} per run.
        self.selection_prompt_template = load_prompt("claim_selection.md")
        self.selection_agent = Agent(
            model,
            output_type=ClaimList,
            deps_type=SelectionDeps,
            model_settings=MODEL_SETTINGS,
        )

        @self.selection_agent.instructions
        def _selection_instructions(ctx: RunContext[SelectionDeps]) -> str:
            return self.selection_prompt_template.replace("{max_claims}", str(ctx.deps.max_claims))

        # Speaker label resolution agent (optional — only if prompt exists).
        try:
            sl_prompt = load_prompt("speaker_labels.md")
            sl_schema = json.dumps(SpeakerLabelsInput.model_json_schema(), indent=2, ensure_ascii=False)
            self.speaker_resolver = Agent(
                model,
                output_type=ResolvedTranscript,
                instructions=sl_prompt.replace("{input_schema}", sl_schema),
                model_settings=MODEL_SETTINGS,
            )
        except FileNotFoundError:
            self.speaker_resolver = None

        logger.info(f"ClaimExtractor initialized with model: {self.model_name}")

    async def _resolve_speaker_labels_async(self, transcript: str, guests: list[str]) -> str:
        """Step 1: Identify speaker label→name mappings and apply them to the transcript."""
        user_message = SpeakerLabelsInput(guests=guests, transcript=transcript).model_dump_json(indent=2)
        result = await self.speaker_resolver.run(user_message)
        for m in result.output.mappings:
            transcript = transcript.replace(m.label, m.name)
        return transcript

    async def resolve_labels_async(self, transcript: str, guests: list[str]) -> str:
        """Resolve generic speaker labels to real names. Returns transcript unchanged if no resolver."""
        if self.speaker_resolver:
            return await self._resolve_speaker_labels_async(transcript, guests)
        return transcript

    async def extract_claims_async(self, resolved_transcript: str, guests: list[str], date: str = "", context: str = "", previous_context: str | None = None) -> List[ExtractedClaim]:
        """Extract claims from an already-resolved transcript. Skips speaker label resolution.

        This is the preferred entry point for the audio pipeline (called after resolve_labels_async).
        """
        logger.info(f"Extracting claims from resolved transcript ({len(resolved_transcript)} chars)")
        user_message = ClaimExtractionInput(
            date=date, guests=guests, context=context,
            transcript=resolved_transcript, previous_block_ending=previous_context,
        ).model_dump_json(indent=2)
        result = await self.claim_extractor.run(user_message)
        logger.info(f"Extraction complete: {len(result.output.claims)} claims found")
        return result.output.claims

    async def extract_async(self, transcript: str, guests: list[str], date: str = "", context: str = "", previous_context: str | None = None) -> List[ExtractedClaim]:
        """Extract claims, resolving speaker labels first (text-block pipeline entry point)."""
        logger.info(f"Extracting claims from transcript ({len(transcript)} chars)")
        if self.speaker_resolver:
            transcript = await self._resolve_speaker_labels_async(transcript, guests)
            logger.info(f"Speaker labels resolved ({len(transcript)} chars)")
        return await self.extract_claims_async(transcript, guests, date=date, context=context, previous_context=previous_context)

    def extract(self, transcript: str, guests: list[str], date: str = "", context: str = "", previous_context: str | None = None) -> List[ExtractedClaim]:
        """Sync wrapper for extract_async()."""
        return asyncio.run(self.extract_async(transcript, guests, date=date, context=context, previous_context=previous_context))

    async def select_async(self, claims: List[dict], max_claims: int = 3) -> List[dict]:
        """Select the top N most fact-checkable claims (autopilot mode)."""
        logger.info(f"Autopilot: selecting up to {max_claims} relevant claims from {len(claims)}...")
        claims_text = "\n".join(
            f"{i + 1}. [{c.get('name', '?')}]: {c.get('claim', '')}"
            for i, c in enumerate(claims)
        )
        user_message = f"Behauptungen:\n{claims_text}"
        try:
            result = await self.selection_agent.run(user_message, deps=SelectionDeps(max_claims=max_claims))
            selected = [{"name": c.name, "claim": c.claim} for c in result.output.claims]
            logger.info(f"Autopilot: selected {len(selected)} claims")
            return selected[:max_claims]
        except Exception:
            logger.exception("Claim selection failed, falling back to all claims (capped)")
            return claims[:max_claims]
```

- [ ] **Step 4: Adapt `test_claim_extraction.py` assertions**

Mechanical conversions (the dict/list outputs are unchanged, so most assertions stay):
- Any test asserting on `genai.Client` / `aio.models.generate_content` calls → delete that assertion (it tested the old transport). Keep the output-shape assertions.
- Any test that called `mock_genai_client` directly → use `mock_claim_extractor` and assert on returned claims.
- A test that needs speaker resolution must override the resolver. Example to add/replace:

```python
from pydantic_ai.models.test import TestModel
from backend.services.claim_extraction import ResolvedTranscript, SpeakerLabelMapping


async def test_resolve_labels_applies_mappings(mock_claim_extractor):
    resolver_out = ResolvedTranscript(mappings=[SpeakerLabelMapping(label="Speaker A", name="Julia Berger")])
    with mock_claim_extractor.speaker_resolver.override(
        model=TestModel(custom_output_args=resolver_out.model_dump())
    ):
        resolved = await mock_claim_extractor.resolve_labels_async(
            "Speaker A: Hallo.", guests=["Julia Berger (CDU)"]
        )
    assert "Julia Berger: Hallo." == resolved
```

- [ ] **Step 5: Run the extraction tests to verify they pass**

Run: `uv run pytest backend/tests/test_claim_extraction.py -v`
Expected: all pass. Fix any leftover assertion that referenced the old transport.

- [ ] **Step 6: Commit**

```bash
git add backend/services/claim_extraction.py backend/tests/conftest.py backend/tests/test_claim_extraction.py
git commit -m "Phase R: rewrite claim_extraction onto PydanticAI agents"
```

---

## Task 6: Rewrite `fact_checker.py` onto PydanticAI

**Files:**
- Modify (rewrite body): `backend/services/fact_checker.py`
- Modify: `backend/tests/conftest.py` (replace `mock_create_agent` / `mock_critique_async` / `mock_fact_checker`)
- Modify: `backend/tests/test_fact_checker.py` (rewrite LangGraph-specific tests)

Keep public surface: `check_claim_async`, `check_claim`, `check_claims_async`, `check_claims`, and the models `FactCheckResponse`, `Source`, `SelfCritiqueInput`, `SelfCritiqueResponse`, `ClaimInput`. Two agents: `self.agent` (fact-check, has `tavily_search` tool, loops) and `self.critique_agent`. `FACT_CHECK_RECURSION_LIMIT` now drives `UsageLimits(request_limit=...)`. The structured-output hacks, `_invoke_with_trace`, `_dump_recursion_trace`, prompt dumps, `FallbackSearchTool`, `MOCK_SEARCH`, and `CostTracker` usage are all removed.

- [ ] **Step 1: Replace the conftest fact-checker fixtures (test scaffolding first)**

In `backend/tests/conftest.py`:

Remove the `from backend.services.cost_tracker import CostTracker` import and both `CostTracker.reset_instance()` calls in the `reset_state` fixture.

Replace `mock_create_agent`, `mock_critique_async`, and `mock_fact_checker` with:
```python
@pytest.fixture
def mock_fact_checker(mock_fact_check_response):
    """FactChecker with both agents overridden by TestModel (no network, no tool calls)."""
    with patch.dict("os.environ", {
        "GEMINI_API_KEY": "test-api-key",
        "TAVILY_API_KEY": "test-tavily-key",
    }):
        from backend.services.fact_checker import FactChecker
        checker = FactChecker()

    # call_tools=[] => go straight to typed output without invoking tavily_search.
    fc_model = TestModel(call_tools=[], custom_output_args=mock_fact_check_response.model_dump())
    crit_model = TestModel(custom_output_args={"confidence": "high", "reason": ""})
    with checker.agent.override(model=fc_model), checker.critique_agent.override(model=crit_model):
        yield checker
```

Keep `mock_fact_check_response` as-is. Delete the `mock_create_agent` and `mock_critique_async` fixtures entirely.

- [ ] **Step 2: Run the fact-checker tests to verify they fail**

Run: `uv run pytest backend/tests/test_fact_checker.py -v`
Expected: FAIL — `FactChecker` has no attribute `agent` / `critique_agent`, and `mock_create_agent` fixture missing.

- [ ] **Step 3: Rewrite `fact_checker.py`**

Replace the entire file with:
```python
"""
Fact Checker Service using PydanticAI with Gemini and Tavily Search.

A typed ReAct-style agent (reason -> tavily_search -> reason -> verdict) plus a
separate self-critique agent that annotates the verdict without gating it.
"""

import os
import json
import asyncio
import logging
from typing import List, Dict, Any, Literal
from datetime import datetime

from pydantic import BaseModel, Field
from pydantic_ai import Agent, UsageLimits, UsageLimitExceeded

from backend.utils import load_prompt
from backend.lang import (
    SOURCE_URL_DESCRIPTION,
    SOURCE_TITLE_DESCRIPTION,
    CONSISTENCY_DESCRIPTION,
    EVIDENCE_DESCRIPTION,
    SOURCES_DESCRIPTION,
    CRITIQUE_CONFIDENCE_DESCRIPTION,
    CRITIQUE_REASON_DESCRIPTION,
)
from .llm_base import build_model, MODEL_SETTINGS
from .search import tavily_search

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-pro"


class Source(BaseModel):
    url: str = Field(description=SOURCE_URL_DESCRIPTION)
    title: str = Field(description=SOURCE_TITLE_DESCRIPTION)


class FactCheckResponse(BaseModel):
    speaker: str
    original_claim: str
    consistency: Literal["hoch", "niedrig", "unklar", "keine Datenlage"] = Field(
        description=CONSISTENCY_DESCRIPTION
    )
    evidence: str = Field(description=EVIDENCE_DESCRIPTION)
    sources: List[Source] = Field(description=SOURCES_DESCRIPTION)


class SelfCritiqueInput(BaseModel):
    """Eingabe für die Selbstkritik eines Faktencheck-Urteils."""
    behauptung: str = Field(description="Die überprüfte Behauptung")
    urteil: Literal["hoch", "niedrig", "unklar", "keine Datenlage"] = Field(description=CONSISTENCY_DESCRIPTION)
    begruendung: str = Field(description="Die Begründung des Faktencheckers")


class SelfCritiqueResponse(BaseModel):
    confidence: Literal["high", "low"] = Field(description=CRITIQUE_CONFIDENCE_DESCRIPTION)
    reason: str = Field(default="", description=CRITIQUE_REASON_DESCRIPTION)


class ClaimInput(BaseModel):
    """Behauptung zur Faktenprüfung."""
    context: str = Field(description="Thematischer Hintergrund der Sendung")
    sprecher: str = Field(description="Name des Sprechers")
    sendedatum: str = Field(description="Monat und Jahr der Sendung, z.B. 'März 2026'")
    behauptung: str = Field(description="Die zu überprüfende Behauptung")


class FactChecker:
    """Fact-checks claims using a PydanticAI agent with Gemini and Tavily."""

    def __init__(self):
        self.model_name = os.getenv("GEMINI_MODEL_FACT_CHECKER", DEFAULT_MODEL)
        self.fallback_model_name = os.getenv("GEMINI_MODEL_FACT_CHECKER_FALLBACK", "gemini-3-flash-preview")

        # Bound the agent loop. Env name kept for backwards compatibility with existing .env/tests.
        self.request_limit = int(os.getenv("FACT_CHECK_RECURSION_LIMIT", "35"))

        # Bake the input schema into the prompt; {current_date} is filled per run.
        prompt = load_prompt("fact_checker.md")
        input_schema = json.dumps(ClaimInput.model_json_schema(), indent=2, ensure_ascii=False)
        self.prompt_template = prompt.replace("{input_schema}", input_schema)

        self.agent = Agent(
            build_model(self.model_name, self.fallback_model_name),
            output_type=FactCheckResponse,
            tools=[tavily_search],
            model_settings=MODEL_SETTINGS,
            retries=2,
        )

        @self.agent.instructions
        def _fact_check_instructions() -> str:
            current_date = datetime.now().strftime("%B %Y")
            return self.prompt_template.replace("{current_date}", current_date)

        # Self-critique agent (separate, annotates only; never gates the verdict).
        self.critique_model_name = os.getenv("GEMINI_MODEL_SELF_CRITIQUE", "gemini-2.5-flash")
        self.self_critique_enabled = os.getenv("SELF_CRITIQUE_ENABLED", "true").lower() != "false"
        self.critique_agent = None
        if self.self_critique_enabled:
            try:
                critique_prompt = load_prompt("self_critique.md")
                critique_schema = json.dumps(SelfCritiqueInput.model_json_schema(), indent=2, ensure_ascii=False)
                self.critique_agent = Agent(
                    build_model(self.critique_model_name),
                    output_type=SelfCritiqueResponse,
                    instructions=critique_prompt.replace("{input_schema}", critique_schema),
                    model_settings=MODEL_SETTINGS,
                )
            except FileNotFoundError:
                self.self_critique_enabled = False

        self.parallel_enabled = os.getenv("FACT_CHECK_PARALLEL", "false").lower() == "true"
        self.max_workers = int(os.getenv("FACT_CHECK_MAX_WORKERS", "5"))

        logger.info(
            f"FactChecker initialized with model: {self.model_name}, "
            f"fallback: {self.fallback_model_name}, request_limit: {self.request_limit}, "
            f"parallel: {self.parallel_enabled}, max_workers: {self.max_workers}"
        )

    @staticmethod
    def _format_episode_date(date: str) -> str:
        """Extract month and year, e.g. '1. März 2026' → 'März 2026'."""
        parts = date.split()
        if parts and parts[0].endswith("."):
            return " ".join(parts[1:])
        return date

    def _build_user_message(self, speaker: str, claim: str, context: str = None, episode_date: str | None = None) -> str:
        return ClaimInput(
            context=context or "",
            sprecher=speaker,
            sendedatum=self._format_episode_date(episode_date) if episode_date else "",
            behauptung=claim,
        ).model_dump_json(indent=2)

    async def check_claim_async(self, speaker: str, claim: str, context: str = None, episode_date: str | None = None) -> Dict[str, Any]:
        """Fact-check a single claim (async)."""
        logger.info(f"Checking claim from {speaker}: {claim[:100]}...")
        user_message = self._build_user_message(speaker, claim, context, episode_date=episode_date)
        return await self._check_claim_async(speaker, claim, user_message)

    def check_claim(self, speaker: str, claim: str, context: str = None, episode_date: str | None = None) -> Dict[str, Any]:
        """Sync wrapper for check_claim_async()."""
        return asyncio.run(self.check_claim_async(speaker, claim, context=context, episode_date=episode_date))

    async def _check_claim_async(self, speaker: str, claim: str, user_message: str) -> Dict[str, Any]:
        limits = UsageLimits(request_limit=self.request_limit)
        try:
            try:
                result = await self.agent.run(user_message, usage_limits=limits)
            except UsageLimitExceeded:
                logger.warning(f"Usage limit hit for '{speaker}', retrying once...")
                result = await self.agent.run(user_message, usage_limits=limits)

            parsed = result.output.model_dump()
            if not parsed.get("speaker"):
                parsed["speaker"] = speaker
            if not parsed.get("original_claim"):
                parsed["original_claim"] = claim

            logger.info(f"Claim checked: consistency = {parsed.get('consistency', 'unknown')}")

            critique = await self._critique_async(
                claim, parsed.get("consistency", ""), parsed.get("evidence", "")
            )
            parsed["double_check"] = critique.confidence == "low"
            parsed["critique_note"] = critique.reason
            return parsed

        except Exception as e:
            logger.exception("Fact-check failed for claim")
            return {
                "speaker": speaker,
                "original_claim": claim,
                "consistency": "unklar",
                "evidence": f"Fehler bei der Überprüfung: {str(e)}",
                "sources": [],
                "double_check": False,
                "critique_note": "",
            }

    async def _critique_async(self, claim: str, consistency: str, evidence: str) -> SelfCritiqueResponse:
        """Self-critique a verdict for confidence. Never blocks or retries the verdict."""
        if not self.self_critique_enabled or not self.critique_agent:
            return SelfCritiqueResponse(confidence="high", reason="")
        user_message = SelfCritiqueInput(
            behauptung=claim, urteil=consistency, begruendung=evidence
        ).model_dump_json(indent=2)
        try:
            result = await self.critique_agent.run(user_message)
            return result.output
        except Exception:
            logger.exception("Self-critique failed, using defaults")
            return SelfCritiqueResponse(confidence="high")

    async def check_claims_async(self, claims: List[Dict[str, str]], context: str = None, episode_date: str | None = None) -> List[Dict[str, Any]]:
        """Fact-check multiple claims (sequential or parallel based on config)."""
        if not claims:
            return []
        logger.info(f"Checking {len(claims)} claims ({'parallel' if self.parallel_enabled else 'sequential'})")
        if self.parallel_enabled:
            return await self._check_claims_parallel_async(claims, context=context, episode_date=episode_date)
        return await self._check_claims_sequential_async(claims, context=context, episode_date=episode_date)

    def check_claims(self, claims: List[Dict[str, str]], context: str = None, episode_date: str | None = None) -> List[Dict[str, Any]]:
        """Sync wrapper for check_claims_async()."""
        return asyncio.run(self.check_claims_async(claims, context=context, episode_date=episode_date))

    async def _check_claims_sequential_async(self, claims, context=None, episode_date=None):
        results = []
        for i, claim_data in enumerate(claims):
            logger.info(f"Processing claim {i + 1}/{len(claims)}")
            speaker = claim_data.get("name", "Unknown")
            claim = claim_data.get("claim", "")
            user_message = self._build_user_message(speaker, claim, context, episode_date=episode_date)
            results.append(await self._check_claim_async(speaker, claim, user_message))
        return results

    async def _check_claims_parallel_async(self, claims, context=None, episode_date=None):
        semaphore = asyncio.Semaphore(self.max_workers)

        async def check_with_limit(claim_data, index):
            async with semaphore:
                speaker = claim_data.get("name", "Unknown")
                claim = claim_data.get("claim", "")
                logger.info(f"Processing claim {index + 1}/{len(claims)}: {claim[:50]}...")
                user_message = self._build_user_message(speaker, claim, context, episode_date=episode_date)
                result = await self._check_claim_async(speaker, claim, user_message)
                logger.info(f"Completed claim {index + 1}/{len(claims)}: {result.get('consistency', 'unknown')}")
                return result

        logger.info(f"Running {len(claims)} claims in parallel (max_concurrency: {self.max_workers})")
        results = await asyncio.gather(
            *[check_with_limit(claim, i) for i, claim in enumerate(claims)],
            return_exceptions=False,
        )
        return list(results)
```

- [ ] **Step 4: Rewrite the LangGraph-specific tests in `test_fact_checker.py`**

Delete or rewrite tests that asserted on LangGraph internals. Specifically:
- `test_check_claim_with_context` (asserted `mock_agent.stream.assert_called_once()`) → rewrite to assert the agent receives the context, using a `FunctionModel` that captures the prompt. Replacement:

```python
from pydantic_ai import models, ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel, AgentInfo
from backend.services.fact_checker import FactCheckResponse

models.ALLOW_MODEL_REQUESTS = False


async def test_check_claim_passes_context_to_agent(mock_fact_checker, mock_fact_check_response):
    captured = {}

    def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        # First user prompt is the claim JSON; capture and return a final text-free output.
        captured["prompt"] = messages[0].parts[-1].content
        # FunctionModel returns the structured output as a tool call to the output tool.
        return ModelResponse(parts=[TextPart(mock_fact_check_response.model_dump_json())])

    # Use TestModel for output simplicity; assert context via the message instead.
    with mock_fact_checker.agent.override(model=FunctionModel(capture)):
        try:
            await mock_fact_checker.check_claim_async(
                speaker="Test Speaker", claim="Test claim", context="Maischberger, 15.01.2024"
            )
        except Exception:
            pass  # output coercion path not under test here
    assert "Maischberger" in captured["prompt"]
```

- `test_recursion_limit_retries_and_succeeds` (used `langgraph.errors.GraphRecursionError`) → rewrite to simulate `UsageLimitExceeded` on first run, success on retry:

```python
import pytest
from pydantic_ai import UsageLimitExceeded
from pydantic_ai.models.test import TestModel


async def test_usage_limit_retries_once_then_succeeds(mock_fact_check_response, monkeypatch):
    from unittest.mock import patch
    with patch.dict("os.environ", {"GEMINI_API_KEY": "k", "TAVILY_API_KEY": "k"}):
        from backend.services.fact_checker import FactChecker
        checker = FactChecker()

    ok_model = TestModel(call_tools=[], custom_output_args=mock_fact_check_response.model_dump())
    calls = {"n": 0}
    real_run = checker.agent.run

    async def flaky_run(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise UsageLimitExceeded("limit")
        return await real_run(*args, **kwargs)

    with checker.agent.override(model=ok_model), \
         patch.object(checker, "critique_agent", None):
        monkeypatch.setattr(checker.agent, "run", flaky_run)
        result = await checker.check_claim_async("Speaker", "Claim")

    assert calls["n"] == 2
    assert result["consistency"] == "hoch"
```

- Any test importing from `langgraph`, `langchain`, or referencing `mock_create_agent` / `_invoke_with_trace` / `structured_response` → delete. The error-path test (`returns "unklar" on failure`) stays but should trigger the failure by overriding the agent with a model that raises; keep its assertion `result["consistency"] == "unklar"`.

- [ ] **Step 5: Run the fact-checker tests to verify they pass**

Run: `uv run pytest backend/tests/test_fact_checker.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/services/fact_checker.py backend/tests/conftest.py backend/tests/test_fact_checker.py
git commit -m "Phase R: rewrite fact_checker onto PydanticAI agent + separate critique agent"
```

---

## Task 7: Wire Logfire into app startup

**Files:**
- Modify: `backend/app.py` (startup)
- Test: `backend/tests/test_observability.py` (extend)

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_observability.py`:
```python
def test_app_imports_configure_logfire():
    """app.py must call configure_logfire at startup."""
    import backend.app as app_mod
    src = __import__("inspect").getsource(app_mod)
    assert "configure_logfire" in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_observability.py::test_app_imports_configure_logfire -v`
Expected: FAIL — `configure_logfire` not referenced in `app.py`.

- [ ] **Step 3: Wire it in**

In `backend/app.py`, locate the existing startup hook (the `@app.on_event("startup")` handler or the `lifespan` function that already clears `/tmp/factcheck_blocks/`). Add near the start of that handler:
```python
from backend.services.observability import configure_logfire
configure_logfire()
```
If startup logic lives at module import time instead, add the import + call right after the FastAPI `app = FastAPI(...)` line.

- [ ] **Step 4: Run test + full app import to verify**

Run: `uv run pytest backend/tests/test_observability.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py backend/tests/test_observability.py
git commit -m "Phase R: configure Logfire at app startup"
```

---

## Task 8: Delete dead modules and purge references

**Files:**
- Delete: `backend/services/cost_tracker.py`
- Delete: `backend/services/studio_graph.py`
- Delete: `backend/services/mock_search.py`
- Delete: `backend/tests/test_cost_tracker.py`
- Modify: any remaining references (langgraph config, `MOCK_SEARCH`, imports)

- [ ] **Step 1: Find any lingering references**

Run:
```bash
grep -rn --include="*.py" -E "cost_tracker|CostTracker|studio_graph|mock_search|MOCK_SEARCH|langchain|langgraph|with_fallbacks|create_agent|GraphRecursionError" backend/
grep -rn -E "langgraph|studio_graph" pyproject.toml langgraph.json 2>/dev/null
```
Expected after Tasks 5–6: hits only in the four files about to be deleted (and possibly a `langgraph.json` at repo root + a `[tool.langgraph]`/scripts entry in `pyproject.toml`).

- [ ] **Step 2: Delete the dead modules and their tests**

```bash
git rm backend/services/cost_tracker.py backend/services/studio_graph.py backend/services/mock_search.py backend/tests/test_cost_tracker.py
```
If a `langgraph.json` exists at the repo root, also `git rm langgraph.json`. Remove any `langgraph dev` script or `[tool.langgraph]` table from `pyproject.toml`.

- [ ] **Step 3: Re-run the reference scan**

Run:
```bash
grep -rn --include="*.py" -E "cost_tracker|CostTracker|studio_graph|mock_search|MOCK_SEARCH|langchain|langgraph|with_fallbacks|create_agent|GraphRecursionError" backend/
```
Expected: **no output** (clean). Fix any remaining import or reference.

- [ ] **Step 4: Lint**

Run: `uv run ruff check backend/`
Expected: no issues. Run `uv run ruff check --fix backend/` if needed.

- [ ] **Step 5: Run the full unit suite**

Run: `uv run pytest backend/tests -m "not integration"`
Expected: all green (count should be the prior 198 minus deleted cost-tracker tests, plus the new llm_base/search/observability tests).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Phase R: remove CostTracker, studio_graph, mock_search and langgraph config"
```

---

## Task 9: Integration verification gate (manual, requires real keys)

**Files:** none (verification only)

This is the merge gate the spec requires — core backend logic must be checked against live behavior before this branch is considered done.

- [ ] **Step 1: Run the integration tests with real keys**

Ensure `.env` has `GEMINI_API_KEY`, `TAVILY_API_KEY`. Run:
```bash
FACT_CHECK_RECURSION_LIMIT=10 uv run pytest backend/tests -m integration -v
```
Expected: integration fact-check + extraction tests pass; a real `tavily_search` tool call happens and a typed `FactCheckResponse` is returned.

- [ ] **Step 2: Production spot-check**

Pick a known episode already fact-checked in production (e.g. `maischberger-2025-09-19`). Run a single claim through `check_claim_async` (script or REPL) and compare `consistency` + the shape/quality of `evidence` and `sources` against the existing production result. Confirm: typed output returned reliably (no plain-text fallback), Tavily restricted to trusted domains, self-critique flags set when expected.

- [ ] **Step 3: (Optional) Verify Logfire locally**

Set `LOGFIRE_TOKEN` in `.env`, run one fact-check, and confirm a trace with token usage + the `tavily_search` span appears in the Logfire UI. Without the token, confirm the run is silent (no errors).

- [ ] **Step 4: Update session memory + handover**

Record outcome in `memory.md` (mark Phase R done/in-progress) and write `handover/YYYY-MM-DD_phase-r-pydanticai-rewrite.md`. Note: branch not merged; merge is the Go-Live step per the roadmap.

---

## Notes for the implementer

- **Do not merge to `main`** as part of this plan. This branch (`worktree-session-multitenancy`) carries Phases 4/3a/R together; merging is a separate Go-Live decision.
- **Public APIs are frozen.** If a router (`audio.py`, `claims.py`, `fact_checks.py`) needs editing, something drifted — stop and re-check; the rewrite must keep method names and return shapes identical.
- **`models.ALLOW_MODEL_REQUESTS = False`** in conftest is the safety net: any test that forgets to override a model fails loudly instead of hitting the real API.
- If `TestModel(custom_output_args=...)` or `call_tools=[]` differ in the installed `pydantic-ai` version, check `uv run python -c "from pydantic_ai.models.test import TestModel; help(TestModel)"` and adjust — the intent is "force this exact typed output, call no tools."
