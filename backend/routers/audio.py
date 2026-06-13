"""
Audio processing endpoints.

Handles audio block reception and transcription pipeline.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Form

from config import Episode
from backend.auth import require_code
from backend.models import ProcessingResponse
from backend.state import processing_lock
from backend.utils import auto_check_enabled, to_dict, truncate
from backend.services.registry import get_transcription_service, get_claim_extractor
from backend.services.transcription import keyterms_from_guests
from backend.routers.claims import process_fact_checks_async
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["audio"])

AUDIO_TMP_DIR = "/tmp/factcheck_blocks"

# Upper bound on a single uploaded audio block, enforced before any paid
# transcription. Our recorder sends ~60-180s blocks (well under this); the cap
# bounds the "one giant block" abuse vector. Overridable via env.
MAX_AUDIO_BLOCK_BYTES = int(os.getenv("MAX_AUDIO_BLOCK_BYTES", str(25 * 1024 * 1024)))


def _audio_file_path(block_id: str) -> str:
    return os.path.join(AUDIO_TMP_DIR, f"{block_id}.wav")


def _cleanup_audio_file(block_id: str):
    try:
        os.remove(_audio_file_path(block_id))
    except FileNotFoundError:
        pass


def _set_event_status(block_id: str, status: str, message: str | None = None, claim_count: int | None = None):
    ev = state.pipeline_events.get(block_id)
    if ev is not None:
        ev["status"] = status
        ev["message"] = message
        if claim_count is not None:
            ev["claim_count"] = claim_count


@router.post('/audio-block', status_code=202, response_model=ProcessingResponse)
async def receive_audio_block(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    session_id: str = Form(...),
    code: dict = Depends(require_code),
):
    """
    Receive audio block from the browser mic recorder and start the pipeline.

    Expected: multipart form data with:
    - audio: recorded audio block (WebM/Opus or MP4, browser-dependent)
    - session_id: Session identifier (required)
    """
    audio_data = await audio.read()
    ep_key = session_id

    # Pre-call guard A — budget. None limit means unlimited.
    limit = code.get("audio_seconds_limit")
    used = code.get("audio_seconds_used", 0)
    if limit is not None and used >= limit:
        raise HTTPException(status_code=429, detail="Audio-Kontingent aufgebraucht")

    # Pre-call guard B — block size, bounded before we pay for transcription.
    if len(audio_data) > MAX_AUDIO_BLOCK_BYTES:
        raise HTTPException(status_code=413, detail="Audio-Block zu groß")

    remaining_seconds = None if limit is None else max(limit - used, 0)

    # Generate block_id here so it can be tracked immediately
    now = datetime.now(timezone.utc)
    block_id = f"block_{int(now.timestamp() * 1000)}"

    logger.info(f"Received audio block {block_id}: {len(audio_data)} bytes, session: {ep_key}")

    # Save audio to temp file for transcription and potential retrigger.
    # Ensure the dir exists here too: startup creates it, but /tmp can be
    # reaped while the backend is long-running (and tests skip the lifespan).
    os.makedirs(AUDIO_TMP_DIR, exist_ok=True)
    audio_path = _audio_file_path(block_id)
    with open(audio_path, "wb") as f:
        f.write(audio_data)

    # Register pipeline event
    state.pipeline_events[block_id] = {
        "block_id": block_id,
        "status": "processing",
        "started_at": now.isoformat(),
        "session_id": ep_key,
        "audio_file": audio_path,
        "message": None,
    }

    # Start background processing (pass path, not bytes, to avoid holding memory in handler)
    background_tasks.add_task(process_audio_pipeline_async, block_id, audio_path, ep_key, code["code"])

    return ProcessingResponse(
        status="processing",
        message="Audio received, processing started",
        block_id=block_id,
        remaining_seconds=remaining_seconds,
    )


async def process_audio_pipeline_async(block_id: str, audio_path: str, session_id: str, code: str | None = None):
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

    db = state.get_db()
    session = await db.get_session(session_id)
    ep = Episode.from_session_row(session) if session else None
    ep_guests = ep.guests if ep else []
    ep_context = ep.context if ep else ""
    ep_conversation_type = ep.conversation_type if ep else "debate"
    ep_keyterms = keyterms_from_guests(ep_guests)

    try:
        logger.info(f"[{block_id}] Starting audio processing pipeline...")

        # Step 1: Transcription (sync call wrapped for async)
        logger.info(f"[{block_id}] Step 1: Transcribing audio...")
        transcription_service = get_transcription_service()
        with open(audio_path, "rb") as f:
            audio_data = f.read()
        try:
            transcript, audio_duration = await asyncio.wait_for(
                asyncio.to_thread(transcription_service.transcribe, audio_data, ep_keyterms),
                timeout=60.0
            )
        except asyncio.TimeoutError:
            logger.error(f"[{block_id}] Transcription timed out after 60 seconds. AssemblyAI is likely stuck in 'processing' state.")
            slow_task.cancel()
            _set_event_status(block_id, "timeout", "Transkription nach 60s abgebrochen (AssemblyAI hängt)")
            return

        slow_task.cancel()
        logger.info(f"[{block_id}] Transcription complete: {len(transcript)} chars")

        # Meter the real audio length against the code's lifetime budget. Runs
        # right after a successful (paid) transcription, before extraction, so
        # even claim-free audio counts. check-before/increment-after: at most one
        # block overshoots the budget, then the code is closed.
        if code is not None and audio_duration > 0:
            await db.increment_audio_seconds(code, int(round(audio_duration)))

        # Grab previous transcript tail for cross-block context.
        # NOTE: two separate lock acquisitions are intentional — label resolution
        # runs outside the lock (it's a slow LLM call). In the rare case of truly
        # concurrent blocks, the last writer wins by resolution speed, not arrival
        # order. In practice, live audio arrives sequentially so this is acceptable.
        async with processing_lock:
            previous_context = state.last_transcript_tail

        # Step 2: Claim extraction (async) — split into resolve + extract
        logger.info(f"[{block_id}] Step 2: Extracting claims...")
        # NOTE: resolve_labels_async and extract_claims_async are required on all
        # ClaimExtractor implementations. The old hasattr/extract_async fallback is
        # removed; any custom extractor must implement these two methods.
        claim_extractor = get_claim_extractor()

        # Step 2a: Resolve speaker labels
        resolved_transcript = await claim_extractor.resolve_labels_async(transcript, ep_guests, conversation_type=ep_conversation_type)
        logger.info(f"[{block_id}] Speaker labels resolved ({len(resolved_transcript)} chars)")

        # Store resolved tail in state for the next block (uses real names, not generic labels)
        async with processing_lock:
            resolved_lines = [line for line in resolved_transcript.strip().splitlines() if line.strip()]
            state.last_transcript_tail = "\n".join(resolved_lines[-3:]) if resolved_lines else None

        # Step 2b: Extract claims from resolved transcript
        claims = await claim_extractor.extract_claims_async(
            resolved_transcript, ep_guests,
            context=ep_context, previous_context=previous_context,
            conversation_type=ep_conversation_type,
        )
        logger.info(f"[{block_id}] Extracted {len(claims)} claims")

        if not claims:
            logger.info(f"[{block_id}] No claims extracted, skipping")
            _set_event_status(block_id, "done", "Keine Claims gefunden", claim_count=0)
            _cleanup_audio_file(block_id)
            return

        # Step 3: Store as pending claims
        pending_block = {
            "block_id": block_id,
            "timestamp": datetime.now().isoformat(),
            "claims_count": len(claims),
            "claims": [to_dict(c) for c in claims],
            "status": "pending",
            "session_id": session_id,
            "text_preview": truncate(transcript)
        }
        await db.add_pending_block(pending_block)

        if auto_check_enabled(session):
            logger.info(f"[{block_id}] Auto-check enabled (session flag or AUTO_APPROVE), selecting best claims...")
            selected = await claim_extractor.select_async(pending_block["claims"], max_claims=3)

            # Insert processing placeholders so viewers see spinners immediately
            now = datetime.now().isoformat()
            placeholder_ids = []
            for claim in selected:
                placeholder = {
                    "sprecher": claim.get("name", ""),
                    "behauptung": claim.get("claim", ""),
                    "consistency": "",
                    "begruendung": "",
                    "quellen": [],
                    "timestamp": now,
                    "session_id": session_id,
                    "status": "processing",
                }
                pid = await db.add_fact_check(placeholder)
                placeholder_ids.append(pid)

            await process_fact_checks_async(selected, session_id, ep_context, placeholder_ids=placeholder_ids)

        logger.info(f"[{block_id}] Pipeline complete. {len(claims)} claims added to pending.")
        _set_event_status(block_id, "done", f"{len(claims)} Claims extrahiert", claim_count=len(claims))
        _cleanup_audio_file(block_id)

    except Exception:
        logger.exception(f"[{block_id}] Pipeline error")
        slow_task.cancel()
        _set_event_status(block_id, "error", "Pipeline-Fehler (siehe Logs)")
        # Keep audio file for retrigger
