"""
Shared utility functions for the backend.
"""

from datetime import datetime
from pathlib import Path


def to_dict(obj):
    """Convert Pydantic model to dict, or return as-is if already a dict."""
    return obj.model_dump() if hasattr(obj, "model_dump") else obj


def truncate(text: str, max_length: int = 200) -> str:
    """Truncate text to max_length, appending '...' if truncated."""
    return text[:max_length] + "..." if len(text) > max_length else text


def build_fact_check_dict(
    result_dict: dict,
    episode_key: str,
    speaker_fallback: str = "",
    claim_fallback: str = "",
) -> dict:
    """Build a fact-check storage dict from a checker result."""
    sources = result_dict.get("sources", [])
    return {
        "sprecher": result_dict.get("speaker", speaker_fallback),
        "behauptung": result_dict.get("original_claim", claim_fallback),
        "consistency": result_dict.get("consistency", "unklar"),
        "begruendung": result_dict.get("evidence", ""),
        "quellen": [to_dict(s) for s in sources] if sources else [],
        "timestamp": datetime.now().isoformat(),
        "episode_key": episode_key,
    }


def load_prompt(filename: str, fallback: str | None = None) -> str:
    """
    Load a prompt template from the prompts directory.

    Tries two locations:
    1. Project root relative (Path(__file__).parent.parent / "prompts" / filename)
    2. Current working directory relative (Path("prompts") / filename)

    Args:
        filename: Name of the prompt file to load
        fallback: Optional fallback content if file not found

    Returns:
        The prompt template content

    Raises:
        FileNotFoundError: If file not found and no fallback provided
    """
    possible_paths = [
        Path(__file__).parent.parent / "prompts" / filename,
        Path("prompts") / filename,
    ]

    for prompt_path in possible_paths:
        try:
            return prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            continue

    if fallback is not None:
        return fallback

    raise FileNotFoundError(
        f"Could not find {filename} prompt file. Tried: {possible_paths}"
    )
