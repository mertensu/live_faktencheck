"""
Configuration endpoints.

Handles show/episode configuration and health checks.
"""

import logging

from fastapi import APIRouter, HTTPException, Depends

from backend.models import (
    HealthResponse,
    ShowsDetailedResponse,
    EpisodesResponse,
)
from config import Episode, get_show_name, get_episodes_for_show
from backend.auth import require_code
from backend.services.trusted_domains import TRUSTED_DOMAINS_BY_CATEGORY
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["config"])


# NOTE: More specific routes MUST come before the wildcard route
# Otherwise /api/config/shows would match /api/config/{session_id}

@router.get('/config/shows', response_model=ShowsDetailedResponse)
async def get_all_shows_endpoint():
    """Return all available sessions as individual entries"""
    try:
        db = state.get_db()
        sessions = await db.list_sessions()
        detailed = sorted(
            [
                {
                    "key": s["session_id"],
                    "name": get_show_name(s["title"]),
                    "date": s.get("date"),
                    "episode_name": Episode.from_session_row(s).episode_name,
                    "type": s.get("type", "show"),
                    "publish": True,
                }
                for s in sessions
                if s.get("visibility") == "public"
            ],
            key=lambda x: x["key"], reverse=True,
        )
        return ShowsDetailedResponse(shows=detailed)
    except Exception as e:
        logger.error(f"Error loading shows: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/config/shows/{show_key}/episodes', response_model=EpisodesResponse)
async def get_episodes_for_show_endpoint(show_key: str):
    """Return all episodes for a show"""
    try:
        episodes = get_episodes_for_show(show_key)
        return EpisodesResponse(episodes=episodes)
    except Exception as e:
        logger.error(f"Error loading episodes for {show_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/config/{session_id}')
async def get_session_config_endpoint(session_id: str):
    """Return configuration for a session"""
    db = state.get_db()
    s = await db.get_session(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    ep = Episode.from_session_row(s)
    payload = {k: v for k, v in s.items() if k != "owner_code"}
    return {**payload, "speakers": ep.speakers, "show_name": get_show_name(s["title"])}


@router.get('/trusted-domains')
async def get_trusted_domains():
    """Return trusted domains grouped by category."""
    return TRUSTED_DOMAINS_BY_CATEGORY


@router.get('/health', response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    db = state.get_db()
    sessions = await db.list_sessions()
    return HealthResponse(
        status="ok",
        active_sessions=len([s for s in sessions if s.get("status") == "active"]),
        pending_blocks=await db.count_pending_blocks(),
        fact_checks=await db.count_fact_checks()
    )


@router.get('/validate-code')
async def validate_code(code: dict = Depends(require_code)):
    """Cheaply validate an access code.

    Reuses ``require_code`` (missing header -> 401, unknown/inactive -> 403).
    Side-effect-free: no DB write, no paid external call. Returns only public
    fields — never the raw code or internal flags.
    """
    return {
        "name": code["name"],
        "quick_check_limit": code["quick_check_limit"],
        "quick_checks_used": code["quick_checks_used"],
    }
