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

# Pipeline event tracking (in-memory, not persisted)
# schema per entry: { block_id, status, started_at, episode_key, audio_file, message }
# status values: "processing" | "slow" | "timeout" | "error" | "done"
pipeline_events: dict[str, dict] = {}

# Claim processing queue (batches enqueued by approve_claims, processed by queue_worker)
claim_queue: asyncio.Queue = asyncio.Queue()

# Reference to the running queue worker task (set during lifespan startup)
queue_worker_task: asyncio.Task | None = None


def get_db() -> Database:
    """Return the active database instance. Raises if not initialized."""
    if db is None:
        raise RuntimeError("Database not initialized. Is the app lifespan running?")
    return db


