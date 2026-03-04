"""
Audio processing endpoints.

Handles audio block reception and transcription pipeline.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form

from backend.models import ProcessingResponse
from backend.state import processing_lock
from backend.utils import to_dict, truncate
from backend.show_config import get_info, get_reference_links
from backend.services.registry import get_transcription_service, get_claim_extractor
from backend.routers.claims import process_fact_checks_async
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["audio"])

AUDIO_TMP_DIR = "/tmp/factcheck_blocks"


def _audio_file_path(block_id: str) -> str:
    return os.path.join(AUDIO_TMP_DIR, f"{block_id}.wav")


def _cleanup_audio_file(block_id: str):
    try:
        os.remove(_audio_file_path(block_id))
    except FileNotFoundError:
        pass


def _set_event_status(block_id: str, status: str, message: str | None = None):
    ev = state.pipeline_events.get(block_id)
    if ev is not None:
        ev["status"] = status
        ev["message"] = message


@router.post('/audio-block', status_code=202, response_model=ProcessingResponse)
async def receive_audio_block(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    episode_key: Optional[str] = Form(default=None),
    info: Optional[str] = Form(default=None)
):
    """
    Receive audio block from listener.py and start processing pipeline.

    Expected: multipart form data with:
    - audio: WAV file
    - episode_key: Episode identifier
    - info: (optional) Context information override
    """
    audio_data = await audio.read()
    ep_key = episode_key or state.current_episode_key or 'test'
    context_info = info or get_info(ep_key)

    # Generate block_id here so it can be tracked immediately
    now = datetime.now(timezone.utc)
    block_id = f"block_{int(now.timestamp() * 1000)}"

    logger.info(f"Received audio block {block_id}: {len(audio_data)} bytes, episode: {ep_key}")

    # Save audio to temp file for transcription and potential retrigger (dir guaranteed by startup)
    audio_path = _audio_file_path(block_id)
    with open(audio_path, "wb") as f:
        f.write(audio_data)

    # Register pipeline event
    state.pipeline_events[block_id] = {
        "block_id": block_id,
        "status": "processing",
        "started_at": now.isoformat(),
        "episode_key": ep_key,
        "audio_file": audio_path,
        "message": None,
    }

    # Start background processing (pass path, not bytes, to avoid holding memory in handler)
    reference_links = get_reference_links(ep_key)
    background_tasks.add_task(process_audio_pipeline_async, block_id, audio_path, ep_key, context_info, reference_links)

    return ProcessingResponse(
        status="processing",
        message="Audio received, processing started",
        episode_key=ep_key,
        block_id=block_id,
    )


async def process_audio_pipeline_async(block_id: str, audio_path: str, episode_key: str, info: str, reference_links: list = None):
    """
    Background pipeline: audio -> transcription -> claim extraction -> pending claims
    """
    async def _mark_slow():
        await asyncio.sleep(30)
        ev = state.pipeline_events.get(block_id)
        if ev is not None and ev["status"] == "processing":
            ev["status"] = "slow"
            logger.warning(f"[{block_id}] Transcription is slow (>30s)")

    slow_task = asyncio.create_task(_mark_slow())

    try:
        logger.info(f"[{block_id}] Starting audio processing pipeline...")

        # Step 1: Transcription (sync call wrapped for async)
        logger.info(f"[{block_id}] Step 1: Transcribing audio...")
        transcription_service = get_transcription_service()
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        try:
            transcript = await asyncio.wait_for(
                asyncio.to_thread(transcription_service.transcribe, audio_data),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            logger.error(f"[{block_id}] Transcription timed out after 60 seconds. AssemblyAI is likely stuck in 'processing' state.")
            slow_task.cancel()
            _set_event_status(block_id, "timeout", "Transkription nach 60s abgebrochen (AssemblyAI hängt)")
            return

        slow_task.cancel()
        logger.info(f"[{block_id}] Transcription complete: {len(transcript)} chars")

        # Grab previous transcript tail for cross-block context, then update it
        async with processing_lock:
            previous_context = state.last_transcript_tail
            # Store the last 3 speaker lines from this transcript for the next block
            transcript_lines = [line for line in transcript.strip().splitlines() if line.strip()]
            state.last_transcript_tail = "\n".join(transcript_lines[-3:]) if transcript_lines else None

        # Step 2: Claim extraction (async)
        logger.info(f"[{block_id}] Step 2: Extracting claims...")
        claim_extractor = get_claim_extractor()
        # Use async method if available, otherwise wrap sync call
        if hasattr(claim_extractor, 'extract_async'):
            claims = await claim_extractor.extract_async(transcript, info, previous_context=previous_context, reference_links=reference_links or [])
        else:
            claims = await asyncio.to_thread(claim_extractor.extract, transcript, info, previous_context=previous_context, reference_links=reference_links or [])
        logger.info(f"[{block_id}] Extracted {len(claims)} claims")

        if not claims:
            logger.info(f"[{block_id}] No claims extracted, skipping")
            _set_event_status(block_id, "done", "Keine Claims gefunden")
            _cleanup_audio_file(block_id)
            return

        # Step 3: Store as pending claims
        db = state.get_db()
        pending_block = {
            "block_id": block_id,
            "timestamp": datetime.now().isoformat(),
            "claims_count": len(claims),
            "claims": [to_dict(c) for c in claims],
            "status": "pending",
            "episode_key": episode_key,
            "info": info,
            "text_preview": truncate(transcript)
        }
        await db.add_pending_block(pending_block)

        if os.getenv("AUTO_APPROVE", "false").lower() == "true":
            logger.info(f"[{block_id}] AUTO_APPROVE enabled, selecting best claims...")
            selected = await claim_extractor.select_async(pending_block["claims"], max_claims=3)
            await process_fact_checks_async(selected, episode_key, info, reference_links=reference_links)

        logger.info(f"[{block_id}] Pipeline complete. {len(claims)} claims added to pending.")
        _set_event_status(block_id, "done", f"{len(claims)} Claims extrahiert")
        _cleanup_audio_file(block_id)

    except Exception:
        logger.exception(f"[{block_id}] Pipeline error")
        slow_task.cancel()
        _set_event_status(block_id, "error", "Pipeline-Fehler (siehe Logs)")
        # Keep audio file for retrigger
