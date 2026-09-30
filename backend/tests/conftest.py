"""
Pytest configuration and fixtures for backend tests.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from pydantic_ai import models

from backend.app import app
from backend import state
from backend.database import Database
from backend.services.registry import reset_services

models.ALLOW_MODEL_REQUESTS = False  # fail loudly if a test ever hits a real model


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
    reset_services()
    yield
    # Cleanup after test
    await db.close()
    state.db = None
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
