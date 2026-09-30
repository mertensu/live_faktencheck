"""
Pydantic models for FastAPI request/response validation.
"""

from pydantic import BaseModel
from typing import List, Optional, Any


# =============================================================================
# Request Models
# =============================================================================

class FactCheckRequest(BaseModel):
    """Request body for POST /api/fact-checks endpoint."""
    # German field names
    sprecher: Optional[str] = None
    behauptung: Optional[str] = None
    consistency: Optional[str] = None
    urteil: Optional[str] = None  # Legacy field, maps to consistency
    begruendung: Optional[str] = None
    quellen: Optional[List[Any]] = None
    # English field names
    speaker: Optional[str] = None
    original_claim: Optional[str] = None
    claim: Optional[str] = None
    evidence: Optional[str] = None
    sources: Optional[List[Any]] = None
    # Session
    session_id: Optional[str] = None


class CreateSessionRequest(BaseModel):
    """Request body for POST /api/sessions."""
    title: str
    date: str = ""
    guests: List[str] = []
    context: str = ""
    type: str = "show"
    conversation_type: str = "debate"
    excluded_speakers: List[str] = []
    keyterms: List[str] = []
    auto_check: bool = False


# =============================================================================
# Response Models
# =============================================================================

class HealthResponse(BaseModel):
    """Response for /api/health endpoint."""
    status: str
    active_sessions: int
    pending_blocks: int = 0  # always 0 since the block pipeline is gone; kept for response shape
    fact_checks: int
    # Real-time in-flight work that a restart would drop: open live streams. The
    # deploy timer reads this to avoid restarting into live work (see
    # deploy/pull-deploy.sh). Distinct from active_sessions, which is a coarse
    # recent-activity count, not a live-work signal.
    in_flight: int = 0


class ShowPreview(BaseModel):
    key: str
    name: str
    date: Optional[str] = None
    episode_name: Optional[str] = None
    type: str = "show"
    publish: bool = False

class ShowsDetailedResponse(BaseModel):
    """Response for /api/config/shows endpoint."""
    shows: List[ShowPreview]


class EpisodesResponse(BaseModel):
    """Response for /api/config/shows/<show_key>/episodes endpoint."""
    episodes: List[dict]


class FactCheckStoredResponse(BaseModel):
    """Response for successful fact-check storage."""
    status: str
    id: int


class SessionResponse(BaseModel):
    """A session as returned by the API."""
    session_id: str
    title: str
    date: str = ""
    guests: List[str] = []
    context: str = ""
    type: str = "show"
    conversation_type: str = "debate"
    excluded_speakers: List[str] = []
    keyterms: List[str] = []
    auto_check: bool = False
    status: str = "active"
    visibility: str = "private"
    created_at: Optional[str] = None
    ended_at: Optional[str] = None
