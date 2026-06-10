"""
Pytest configuration and fixtures for backend tests.
"""

from contextlib import ExitStack

import nest_asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from pydantic_ai import models
from pydantic_ai.models.test import TestModel

from backend.app import app
from backend import state
from backend.database import Database
from backend.services.claim_extraction import ExtractedClaim, ClaimList, ResolvedTranscript
from backend.services.cost_tracker import CostTracker
from backend.services.registry import reset_services

models.ALLOW_MODEL_REQUESTS = False  # fail loudly if a test ever hits a real model

# Allow nested event loops - fixes LangChain agent hanging in pytest
# See: https://github.com/pytest-dev/pytest-asyncio/discussions/546
nest_asyncio.apply()


# Access code seeded into every test DB so gated endpoints are reachable.
TEST_ACCESS_CODE = "test-code"


# =============================================================================
# State Reset Fixture
# =============================================================================

@pytest.fixture(autouse=True)
async def reset_state():
    """Reset shared state and provide fresh in-memory DB before each test."""
    db = Database(":memory:")
    await db.connect()
    await db.add_code(TEST_ACCESS_CODE, "tester")
    state.db = db
    state.last_transcript_tail = None
    state.pipeline_events.clear()
    CostTracker.reset_instance()
    reset_services()
    yield
    # Cleanup after test
    await db.close()
    state.db = None
    state.last_transcript_tail = None
    state.pipeline_events.clear()
    CostTracker.reset_instance()
    reset_services()


# =============================================================================
# FastAPI Test Client Fixture
# =============================================================================

@pytest.fixture
async def client():
    """Async HTTP client that sends a valid access code by default."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"X-Access-Code": TEST_ACCESS_CODE},
    ) as ac:
        yield ac


@pytest.fixture
async def no_auth_client():
    """Async HTTP client that sends no access code (for gate tests)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# =============================================================================
# Mock Fixtures for ClaimExtractor
# =============================================================================

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
    sl_model = TestModel(custom_output_args=ResolvedTranscript(mappings=[]).model_dump())
    with ExitStack() as stack:
        stack.enter_context(extractor.claim_extractor.override(model=claims_model))
        stack.enter_context(extractor.selection_agent.override(model=claims_model))
        # speaker_resolver is None only when the prompt file is missing; guard for safety.
        if extractor.speaker_resolver is not None:
            stack.enter_context(extractor.speaker_resolver.override(model=sl_model))
        yield extractor


# =============================================================================
# Mock Fixtures for FactChecker
# =============================================================================

@pytest.fixture
def mock_fact_check_response():
    """Default mock response for fact-checking."""
    from backend.services.fact_checker import FactCheckResponse, Source
    return FactCheckResponse(
        speaker="Test Speaker",
        original_claim="Test claim statement",
        consistency="hoch",
        evidence="Dies ist eine verifizierte Aussage basierend auf offiziellen Quellen.",
        sources=[
            Source(url="https://example.com/source1", title="Example Source 1"),
            Source(url="https://example.com/source2", title="Example Source 2"),
        ],
    )


@pytest.fixture
def mock_create_agent(mock_fact_check_response):
    """Mock the create_agent function for FactChecker."""
    with patch("backend.services.fact_checker.create_agent") as mock_create:
        mock_agent = MagicMock()

        final_state = {
            "structured_response": mock_fact_check_response,
            "messages": []
        }

        # Mock stream (used by _invoke_with_trace) as a generator yielding one final state
        def mock_stream(*args, **kwargs):
            yield final_state
        mock_agent.stream = MagicMock(side_effect=mock_stream)

        # Mock invoke (used for retries) and ainvoke for compatibility
        mock_agent.invoke = MagicMock(return_value=final_state)
        mock_agent.ainvoke = AsyncMock(return_value=final_state)

        mock_create.return_value = mock_agent
        yield mock_create


@pytest.fixture
def mock_critique_async():
    """Mock _critique_async to return a non-flagged default (no network calls)."""
    from backend.services.fact_checker import SelfCritiqueResponse
    default = SelfCritiqueResponse(confidence="high")
    with patch(
        "backend.services.fact_checker.FactChecker._critique_async",
        new=AsyncMock(return_value=default),
    ) as mock:
        yield mock


@pytest.fixture
def mock_fact_checker(mock_create_agent, mock_critique_async):
    """Fixture that provides a FactChecker with mocked LangChain agent."""
    with patch.dict("os.environ", {
        "GEMINI_API_KEY": "test-api-key",
        "TAVILY_API_KEY": "test-tavily-key",
    }):
        from backend.services.fact_checker import FactChecker
        checker = FactChecker()
        yield checker


# =============================================================================
# Combined Service Mocks (for API integration tests)
# =============================================================================

@pytest.fixture
def mock_all_services(mock_claim_extractor, mock_fact_checker):
    """Provide both mocked services for API-level tests."""
    return {"claim_extractor": mock_claim_extractor, "fact_checker": mock_fact_checker}


# =============================================================================
# Sample Data Fixtures
# =============================================================================

@pytest.fixture
def sample_transcript():
    """Sample transcript for testing claim extraction."""
    return """
    Speaker A: Deutschland hat über 80 Millionen Einwohner.
    Speaker B: Das stimmt, und die Wirtschaft wächst um 2 Prozent pro Jahr.
    Speaker A: Die Arbeitslosenquote liegt bei etwa 5 Prozent.
    """


@pytest.fixture
def sample_claims():
    """Sample claims for testing fact-checking."""
    return [
        {"name": "Speaker A", "claim": "Deutschland hat über 80 Millionen Einwohner."},
        {"name": "Speaker B", "claim": "Die Wirtschaft wächst um 2 Prozent pro Jahr."},
    ]


@pytest.fixture
def sample_fact_check():
    """Sample fact-check result for testing."""
    return {
        "speaker": "Test Speaker",
        "original_claim": "Test claim",
        "consistency": "hoch",
        "evidence": "Verifizierte Information.",
        "sources": ["https://example.com"],
        "episode": "test-episode",
    }
