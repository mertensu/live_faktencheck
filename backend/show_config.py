"""
Re-export show/episode config functions from root config.py.

All backend modules should import from here instead of the root config directly.
"""

try:
    from config import (
        get_show_config,
        get_speakers,
        get_info,
        get_all_shows,
        get_episodes_for_show,
        get_all_episodes,
        DEFAULT_SHOW,
        SHOW_CONFIG,
    )
except ImportError:
    import logging
    logging.getLogger(__name__).warning("config.py not found. Using default configuration.")

    SHOW_CONFIG = {}
    DEFAULT_SHOW = "test"

    def get_show_config(episode_key=None):
        return {"speakers": [], "info": "", "name": "Unknown", "description": ""}

    def get_speakers(episode_key=None):
        return []

    def get_info(episode_key=None):
        return ""

    def get_all_shows():
        return []

    def get_episodes_for_show(show_key):
        return []

    def get_all_episodes():
        return []
