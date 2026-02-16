"""
Configuration endpoints.

Handles show/episode configuration and health checks.
"""

import logging

from fastapi import APIRouter, HTTPException

from backend.models import (
    SetEpisodeRequest,
    HealthResponse,
    ShowsDetailedResponse,
    EpisodesResponse,
)
from backend.show_config import get_show_config, get_episodes_for_show
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["config"])


# NOTE: More specific routes MUST come before the wildcard route
# Otherwise /api/config/shows would match /api/config/{episode_key}

@router.get('/config/shows', response_model=ShowsDetailedResponse)
async def get_all_shows_endpoint():
    """Return all available episodes as individual entries"""
    try:
        from backend.show_config import SHOW_CONFIG
        detailed_shows = []

        for episode_key, config in SHOW_CONFIG.items():
            detailed_shows.append({
                "key": episode_key,
                "name": config.get("name", episode_key.capitalize()),
                "description": config.get("description", ""),
                "info": config.get("info", ""),
                "type": config.get("type", "show"),
                "speakers": config.get("speakers", []),
                "episode_name": config.get("episode_name", ""),
            })

        # Sort by key (reverse for newest first)
        detailed_shows.sort(key=lambda x: x["key"], reverse=True)

        return ShowsDetailedResponse(shows=detailed_shows)
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


@router.get('/config/{episode_key}')
async def get_episode_config_endpoint(episode_key: str):
    """Return configuration for an episode"""
    try:
        config = get_show_config(episode_key)
        return config
    except Exception as e:
        logger.error(f"Error loading config for {episode_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post('/set-episode')
async def set_current_episode(request: SetEpisodeRequest):
    """Set the current episode (called by listener). Clears old pending claims."""
    episode_key = request.episode_key or request.episode
    if episode_key:
        state.current_episode_key = episode_key
        # Clear all pending claims from previous sessions
        db = state.get_db()
        deleted = await db.clear_pending_blocks()
        if deleted:
            logger.info(f"Cleared {deleted} pending claim blocks from previous session")
        logger.info(f"Current episode set: {episode_key}")
        return {"status": "success", "episode_key": episode_key, "cleared_pending": deleted}
    else:
        raise HTTPException(status_code=400, detail="episode_key missing")


@router.get('/health', response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    db = state.get_db()
    return HealthResponse(
        status="ok",
        current_episode=state.current_episode_key,
        pending_blocks=await db.count_pending_blocks(),
        fact_checks=await db.count_fact_checks()
    )
