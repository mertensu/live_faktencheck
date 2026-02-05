"""
Audio processing endpoints.

Handles audio block reception and transcription pipeline.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, UploadFile, File, Form

from backend.models import ProcessingResponse
from backend.state import pending_claims_blocks, processing_lock, to_dict
from backend.show_config import get_info
from backend.services.registry import get_transcription_service, get_claim_extractor
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["audio"])


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

    logger.info(f"Received audio block: {len(audio_data)} bytes, episode: {ep_key}")

    # Start background processing
    background_tasks.add_task(process_audio_pipeline_async, audio_data, ep_key, context_info)

    return ProcessingResponse(
        status="processing",
        message="Audio received, processing started",
        episode_key=ep_key
    )


async def process_audio_pipeline_async(audio_data: bytes, episode_key: str, info: str):
    """
    Background pipeline: audio -> transcription -> claim extraction -> pending claims
    """
    block_id = f"block_{int(datetime.now().timestamp() * 1000)}"

    try:
        logger.info(f"[{block_id}] Starting audio processing pipeline...")

        # Step 1: Transcription (sync call wrapped for async)
        logger.info(f"[{block_id}] Step 1: Transcribing audio...")
        transcription_service = get_transcription_service()
        transcript = await asyncio.to_thread(transcription_service.transcribe, audio_data)
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
            claims = await claim_extractor.extract_async(transcript, info, previous_context=previous_context)
        else:
            claims = await asyncio.to_thread(claim_extractor.extract, transcript, info, previous_context=previous_context)
        logger.info(f"[{block_id}] Extracted {len(claims)} claims")

        if not claims:
            logger.info(f"[{block_id}] No claims extracted, skipping")
            return

        # Step 3: Store as pending claims
        async with processing_lock:
            pending_block = {
                "block_id": block_id,
                "timestamp": datetime.now().isoformat(),
                "claims_count": len(claims),
                "claims": [to_dict(c) for c in claims],
                "status": "pending",
                "episode_key": episode_key,
                "info": info,
                "transcript_preview": transcript[:200] + "..." if len(transcript) > 200 else transcript
            }
            pending_claims_blocks.append(pending_block)

        logger.info(f"[{block_id}] Pipeline complete. {len(claims)} claims added to pending.")

    except Exception:
        logger.exception(f"[{block_id}] Pipeline error")
