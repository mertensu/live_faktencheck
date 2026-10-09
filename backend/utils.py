"""
Shared utility functions for the backend.
"""

import os
from datetime import datetime
from pathlib import Path


def to_dict(obj):
    """Convert Pydantic model to dict, or return as-is if already a dict."""
    return obj.model_dump() if hasattr(obj, "model_dump") else obj


def build_fact_check_dict(
    result_dict: dict,
    session_id: str,
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
        "session_id": session_id,
        "status": "",
        "double_check": result_dict.get("double_check", False),
        "critique_note": result_dict.get("critique_note", ""),
    }


def log_text(text: str | None, limit: int | None = None) -> str:
    """Spoken content for a log line: only its length, unless LOG_SENTENCE_TEXT is set.

    Transcript sentences and claims are personal data; the logs keep them out by default
    (see the privacy policy). Set LOG_SENTENCE_TEXT=true on staging to debug with text.
    """
    text = text or ""
    if os.getenv("LOG_SENTENCE_TEXT", "").strip().lower() in ("1", "true", "yes"):
        return repr(text[:limit] if limit else text)
    return f"<{len(text)} chars>"


def load_prompt(filename: str, fallback: str | None = None) -> str:
    """Load a prompt template from the prompts directory."""
    roots = [
        Path(__file__).parent.parent / "prompts",
        Path("prompts"),
    ]

    for root in roots:
        try:
            return (root / filename).read_text(encoding="utf-8")
        except FileNotFoundError:
            continue

    if fallback is not None:
        return fallback

    raise FileNotFoundError(f"Could not find prompt file: {filename}")
