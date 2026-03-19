"""
Pipeline status endpoints.

Provides visibility into in-flight and failed audio processing blocks,
and allows admin retrigger of failed blocks.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["pipeline"])

# Prune done events from memory after this many seconds
_PRUNE_DONE_AFTER_SECONDS = 300  # 5 minutes


def _elapsed_seconds(iso_str: str, now: datetime) -> float:
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (now - dt).total_seconds()
    except Exception:
        return 0.0


@router.get("/pipeline-status")
async def get_pipeline_status():
    """
    Returns all pipeline events that are not yet done, plus done events < 2 min old.
    Auto-prunes done events older than 5 minutes from memory.
    """
    now = datetime.now(timezone.utc)
    result = []
    to_delete = []

    for bid, ev in state.pipeline_events.items():
        elapsed = _elapsed_seconds(ev["started_at"], now)
        if ev["status"] == "done" and elapsed > _PRUNE_DONE_AFTER_SECONDS:
            to_delete.append(bid)
            continue
        if ev["status"] != "done" or elapsed < 120:
            result.append({**ev, "elapsed_seconds": int(elapsed)})

    for bid in to_delete:
        del state.pipeline_events[bid]

    return result


@router.post("/pipeline-status/{block_id}/retrigger")
async def retrigger_pipeline(block_id: str):
    """
    Retrigger a failed (timeout/error) pipeline block from its saved temp file.
    """
    # Lazy import to avoid circular dependency
    from backend.routers.audio import process_audio_pipeline_async

    ev = state.pipeline_events.get(block_id)
    if ev is None:
        raise HTTPException(status_code=404, detail=f"Kein Pipeline-Event für Block '{block_id}' gefunden")

    if ev["status"] not in ("timeout", "error"):
        raise HTTPException(
            status_code=400,
            detail=f"Block '{block_id}' hat Status '{ev['status']}' — nur timeout/error können neu gestartet werden"
        )

    audio_file = ev.get("audio_file")
    if not audio_file or not os.path.exists(audio_file):
        raise HTTPException(
            status_code=404,
            detail=f"Audio-Datei für Block '{block_id}' nicht gefunden (Pfad: {audio_file})"
        )

    ep_key = ev.get("episode_key") or state.current_episode_key or ""

    # Reset event to processing
    ev["status"] = "processing"
    ev["started_at"] = datetime.now(timezone.utc).isoformat()
    ev["message"] = None

    logger.info(f"[{block_id}] Retrigger requested — restarting pipeline")

    asyncio.create_task(process_audio_pipeline_async(block_id, audio_file, ep_key))

    return {"status": "processing", "block_id": block_id, "message": "Pipeline neu gestartet"}
