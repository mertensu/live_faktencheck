"""
Shared utility functions for the backend.
"""

import os
import tomllib
from datetime import datetime
from functools import lru_cache
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
        "status": "",
    }


def _lang_variants(filename: str) -> list[str]:
    """Return filenames to try in order, inserting a lang-specific variant first if LANG is set."""
    lang = os.getenv("LANG", "").lower()
    if lang:
        stem, _, suffix = filename.rpartition(".")
        if stem:
            return [f"{stem}_{lang}.{suffix}", filename]
    return [filename]


@lru_cache(maxsize=1)
def load_lang_config() -> dict:
    """Load the language-specific schema config from prompts/lang_de.toml (or lang.toml)."""
    # Normalize LANG=de_DE.UTF-8 → "de" (just the 2-letter language code)
    raw_lang = os.getenv("LANG", "")
    lang = raw_lang.split("_")[0].split(".")[0].lower()
    candidates = [f"lang_{lang}.toml", "lang.toml"] if lang else ["lang.toml"]
    roots = [Path(__file__).parent.parent / "prompts", Path("prompts")]
    for candidate in candidates:
        for root in roots:
            try:
                with open(root / candidate, "rb") as f:
                    return tomllib.load(f)
            except FileNotFoundError:
                continue
    raise FileNotFoundError(f"Could not find lang config (variants tried: {candidates})")


def load_prompt(filename: str, fallback: str | None = None) -> str:
    """
    Load a prompt template from the prompts directory.

    If LANG env var is set (e.g. LANG=de), tries a language-specific variant
    first (e.g. fact_checker_de.md) before falling back to the base file.

    Tries two filesystem locations for each candidate filename:
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
    candidates = _lang_variants(filename)
    roots = [
        Path(__file__).parent.parent / "prompts",
        Path("prompts"),
    ]

    for candidate in candidates:
        for root in roots:
            try:
                return (root / candidate).read_text(encoding="utf-8")
            except FileNotFoundError:
                continue

    if fallback is not None:
        return fallback

    raise FileNotFoundError(
        f"Could not find {filename} prompt file (lang variants tried: {candidates})"
    )
