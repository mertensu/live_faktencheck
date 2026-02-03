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
from backend.state import fact_checks, pending_claims_blocks
from backend.show_config import get_show_config, get_all_shows, get_episodes_for_show
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["config"])


# NOTE: More specific routes MUST come before the wildcard route
# Otherwise /api/config/shows would match /api/config/{episode_key}

@router.get('/config/shows', response_model=ShowsDetailedResponse)
async def get_all_shows_endpoint():
    """Return all available shows with details from latest episode"""
    try:
        show_keys = get_all_shows()
        detailed_shows = []

        for key in show_keys:
            # Get episodes to find latest info
            episodes = get_episodes_for_show(key)

            # Default values
            name = key.capitalize()
            description = ""
            info = ""
            speakers = []

            if episodes:
                # Use latest episode for info
                latest = episodes[0]
                config = latest.get('config', {})
                name = config.get('name', name)
                description = config.get('description', "")
                info = config.get('info', "")
                type_ = config.get('type', "show")
                speakers = config.get('speakers', [])
            else:
                type_ = "show"  # Default

            detailed_shows.append({
                "key": key,
                "name": name,
                "description": description,
                "info": info,
                "type": type_,
                "speakers": speakers
            })

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
    """Set the current episode (called by listener)"""
    episode_key = request.episode_key or request.episode
    if episode_key:
        state.current_episode_key = episode_key
        logger.info(f"Current episode set: {episode_key}")
        return {"status": "success", "episode_key": episode_key}
    else:
        raise HTTPException(status_code=400, detail="episode_key missing")


@router.get('/health', response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    return HealthResponse(
        status="ok",
        current_episode=state.current_episode_key,
        pending_blocks=len(pending_claims_blocks),
        fact_checks=len(fact_checks)
    )
