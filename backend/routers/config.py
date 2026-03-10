"""
Configuration endpoints.

Handles show/episode configuration and health checks.
"""

import dataclasses
import logging

from fastapi import APIRouter, HTTPException

from backend.models import (
    SetEpisodeRequest,
    HealthResponse,
    ShowsDetailedResponse,
    EpisodesResponse,
)
from config import EPISODES, get_show_name, get_episodes_for_show
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["config"])


# NOTE: More specific routes MUST come before the wildcard route
# Otherwise /api/config/shows would match /api/config/{episode_key}

@router.get('/config/shows', response_model=ShowsDetailedResponse)
async def get_all_shows_endpoint():
    """Return all available episodes as individual entries"""
    try:
        detailed_shows = sorted(
            [
                {
                    "key": ep.key,
                    "name": get_show_name(ep.show),
                    "date": ep.date,
                    "episode_name": ep.episode_name,
                    "type": ep.type,
                    "publish": ep.publish,
                }
                for ep in EPISODES.values()
            ],
            key=lambda x: x["key"],
            reverse=True,
        )
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
    episode = EPISODES.get(episode_key)
    if episode is None:
        raise HTTPException(status_code=404, detail=f"Unknown episode: {episode_key}")
    return {**dataclasses.asdict(episode), "speakers": episode.speakers}


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
