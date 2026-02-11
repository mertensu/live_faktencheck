"""
Shared state for the fact-check backend.

Runtime state (episode, transcript context) and database reference.
Fact-checks and pending claims are stored in SQLite via the Database class.
"""

import asyncio

from backend.database import Database

# Runtime state (not persisted)
current_episode_key: str | None = None
last_transcript_tail: str | None = None

# Lock for concurrent access
processing_lock = asyncio.Lock()

# Database instance (set during app lifespan)
db: Database | None = None


def get_db() -> Database:
    """Return the active database instance. Raises if not initialized."""
    if db is None:
        raise RuntimeError("Database not initialized. Is the app lifespan running?")
    return db


def to_dict(obj):
    """Convert Pydantic model to dict, or return as-is if already a dict."""
    return obj.model_dump() if hasattr(obj, "model_dump") else obj
