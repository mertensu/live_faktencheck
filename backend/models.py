"""
Pydantic models for FastAPI request/response validation.
"""

from pydantic import BaseModel
from typing import List, Optional, Any


# =============================================================================
# Request Models
# =============================================================================

class TextBlockRequest(BaseModel):
    """Request body for /api/text-block endpoint."""
    text: str
    headline: str = ""
    publication_date: Optional[str] = None
    source_id: Optional[str] = None


class ClaimApprovalRequest(BaseModel):
    """Request body for /api/approve-claims endpoint."""
    claims: List[dict]
    block_id: Optional[str] = None
    episode_key: Optional[str] = None


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
    # Episode
    episode_key: Optional[str] = None
    episode: Optional[str] = None


class PendingClaimsRequest(BaseModel):
    """Request body for POST /api/pending-claims endpoint."""
    block_id: Optional[str] = None
    timestamp: Optional[str] = None
    claims: List[dict] = []
    episode_key: Optional[str] = None


class SetEpisodeRequest(BaseModel):
    """Request body for /api/set-episode endpoint."""
    episode_key: Optional[str] = None
    episode: Optional[str] = None


class ClaimUpdateRequest(BaseModel):
    """Request body for PUT /api/fact-checks/{id} endpoint (re-send with overwrite)."""
    name: str
    claim: str
    episode_key: Optional[str] = None
    fact_check_id: Optional[int] = None
    original_claim: Optional[str] = None


# =============================================================================
# Response Models
# =============================================================================

class StatusResponse(BaseModel):
    """Generic status response."""
    status: str
    message: Optional[str] = None


class ProcessingResponse(BaseModel):
    """Response for endpoints that start background processing."""
    status: str
    message: Optional[str] = None
    episode_key: Optional[str] = None
    claims_count: Optional[int] = None
    source_id: Optional[str] = None
    block_id: Optional[str] = None


class HealthResponse(BaseModel):
    """Response for /api/health endpoint."""
    status: str
    current_episode: Optional[str]
    pending_blocks: int
    fact_checks: int


class ShowPreview(BaseModel):
    key: str
    name: str
    description: Optional[str] = None
    info: Optional[str] = None
    type: str = "show"
    speakers: List[str] = []
    episode_name: Optional[str] = None

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
