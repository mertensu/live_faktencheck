"""
Shared utility functions for the backend.
"""

from pathlib import Path


def to_dict(obj):
    """Convert Pydantic model to dict, or return as-is if already a dict."""
    return obj.model_dump() if hasattr(obj, "model_dump") else obj


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
