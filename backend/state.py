"""
Shared state for the fact-check backend.

In-memory storage for fact-checks and pending claims.
"""

import asyncio

# In-memory storage
fact_checks: list = []
pending_claims_blocks: list = []
current_episode_key: str | None = None

# Last few speaker turns from the previous transcript block, for cross-block continuity
last_transcript_tail: str | None = None

# Lock for concurrent access
processing_lock = asyncio.Lock()


def to_dict(obj):
    """Convert Pydantic model to dict, or return as-is if already a dict."""
    return obj.model_dump() if hasattr(obj, "model_dump") else obj
