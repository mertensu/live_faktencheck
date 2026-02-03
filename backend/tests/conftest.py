"""
Pytest configuration and fixtures for backend tests.
"""

import nest_asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport

from backend.app import app
from backend import state
from backend.services.claim_extraction import ExtractedClaim, ClaimList
from backend.services.fact_checker import FactCheckResponse, Source
from backend.services.cost_tracker import CostTracker

# Allow nested event loops - fixes LangChain agent hanging in pytest
# See: https://github.com/pytest-dev/pytest-asyncio/discussions/546
nest_asyncio.apply()


# =============================================================================
# State Reset Fixture
# =============================================================================

@pytest.fixture(autouse=True)
def reset_state():
    """Reset shared state before each test."""
    state.fact_checks.clear()
    state.pending_claims_blocks.clear()
    state.current_episode_key = None
    CostTracker.reset_instance()
    yield
    # Cleanup after test
    state.fact_checks.clear()
    state.pending_claims_blocks.clear()
    state.current_episode_key = None
    CostTracker.reset_instance()


# =============================================================================
# FastAPI Test Client Fixture
# =============================================================================

@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# =============================================================================
# Mock Fixtures for ClaimExtractor
# =============================================================================

@pytest.fixture
def mock_gemini_response():
    """Default mock response for Gemini claim extraction."""
    return ClaimList(claims=[
        ExtractedClaim(name="Test Speaker", claim="Test claim statement"),
        ExtractedClaim(name="Another Speaker", claim="Another test claim"),
    ])


@pytest.fixture
def mock_genai_client(mock_gemini_response):
    """Mock the genai.Client for ClaimExtractor."""
    with patch("backend.services.claim_extraction.genai.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Mock the async generate_content method
        mock_response = MagicMock()
        mock_response.parsed = mock_gemini_response
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        yield mock_client


@pytest.fixture
def mock_claim_extractor(mock_genai_client):
    """Fixture that provides a ClaimExtractor with mocked Gemini client."""
    with patch.dict("os.environ", {"GEMINI_API_KEY": "test-api-key"}):
        from backend.services.claim_extraction import ClaimExtractor
        extractor = ClaimExtractor()
        yield extractor


# =============================================================================
# Mock Fixtures for FactChecker
# =============================================================================

@pytest.fixture
def mock_fact_check_response():
    """Default mock response for fact-checking."""
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

        # Mock both invoke (used in asyncio.to_thread) and ainvoke for compatibility
        mock_agent.invoke = MagicMock(return_value={
            "structured_response": mock_fact_check_response,
            "messages": []  # Empty messages for cost tracking
        })
        mock_agent.ainvoke = AsyncMock(return_value={
            "structured_response": mock_fact_check_response,
            "messages": []
        })

        mock_create.return_value = mock_agent
        yield mock_create


@pytest.fixture
def mock_fact_checker(mock_create_agent):
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
def mock_all_services(mock_genai_client, mock_create_agent):
    """Mock both ClaimExtractor and FactChecker services."""
    with patch.dict("os.environ", {
        "GEMINI_API_KEY": "test-api-key",
        "TAVILY_API_KEY": "test-tavily-key",
    }):
        yield {
            "genai_client": mock_genai_client,
            "create_agent": mock_create_agent,
        }


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
