"""
Shared state for the fact-check backend.

Runtime state and database reference. Fact-checks and sessions are stored in
SQLite via the Database class.
"""

from backend.database import Database

# Database instance (set during app lifespan)
db: Database | None = None

# Live streaming sessions (in-memory, not persisted). Keyed by the WebSocket
# connection so the /api/stream endpoint can look up and tear down its session.
# Values are backend.services.streaming.StreamingSession instances.
streaming_sessions: dict[str, object] = {}


def get_db() -> Database:
    """Return the active database instance. Raises if not initialized."""
    if db is None:
        raise RuntimeError("Database not initialized. Is the app lifespan running?")
    return db
