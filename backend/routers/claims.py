"""
Claims management endpoints.

Handles pending claims and text-based claim extraction.
"""

import asyncio
import logging
import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks

from backend.models import (
    TextBlockRequest,
    ClaimApprovalRequest,
    PendingClaimsRequest,
    ProcessingResponse,
)
from backend.utils import to_dict, truncate, build_fact_check_dict
import backend.state as state

from config import EPISODES
from backend.services.registry import get_claim_extractor, get_fact_checker

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["claims"])


# =============================================================================
# Text Processing Pipeline (skip transcription)
# =============================================================================

@router.post('/text-block', status_code=202, response_model=ProcessingResponse)
async def receive_text_block(
    request: TextBlockRequest,
    background_tasks: BackgroundTasks
):
    """
    Receive text directly for claim extraction (skip transcription).

    Expected JSON:
    - text: Article/text content to extract claims from
    - headline: Context/headline for the article
    - publication_date: (optional) Publication date, defaults to current month/year
    - source_id: (optional) Identifier for the source, defaults to article-YYYYMMDD-HHMMSS
    """
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="No text provided")

    source_id = request.source_id or f"article-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    logger.info(f"Received text block: {len(request.text)} chars, headline: {request.headline[:50]}...")

    # Submit to background processing (claim extraction only, skip transcription)
    background_tasks.add_task(
        process_text_pipeline_async,
        request.text,
        request.headline,
        source_id,
        request.publication_date
    )

    return ProcessingResponse(
        status="accepted",
        message="Text block received, processing claims...",
        source_id=source_id
    )


async def process_text_pipeline_async(text: str, headline: str, source_id: str, publication_date: str = None):
    """
    Background pipeline: text -> claim extraction -> pending claims
    (Skips transcription step - for articles, press releases, etc.)
    """
    block_id = f"text_{int(datetime.now().timestamp() * 1000)}"

    try:
        logger.info(f"[{block_id}] Starting text processing pipeline...")

        # Claim extraction
        logger.info(f"[{block_id}] Extracting claims from article...")
        claim_extractor = get_claim_extractor()

        claims = await claim_extractor.extract_async(text, guests=[], date=publication_date or "", context=headline)
        logger.info(f"[{block_id}] Extracted {len(claims)} claims")

        if not claims:
            logger.info(f"[{block_id}] No claims extracted, skipping")
            return

        # Store as pending claims
        db = state.get_db()
        pending_block = {
            "block_id": block_id,
            "timestamp": datetime.now().isoformat(),
            "claims_count": len(claims),
            "claims": [to_dict(c) for c in claims],
            "status": "pending",
            "source_id": source_id,
            "episode_key": state.current_episode_key or "test",
            "headline": headline,
            "text_preview": truncate(text)
        }
        await db.add_pending_block(pending_block)

        if os.getenv("AUTO_APPROVE", "false").lower() == "true":
            logger.info(f"[{block_id}] AUTO_APPROVE enabled, selecting best claims...")
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
                    "episode_key": pending_block["episode_key"],
                    "status": "processing",
                }
                pid = await db.add_fact_check(placeholder)
                placeholder_ids.append(pid)
            await process_fact_checks_async(selected, pending_block["episode_key"], headline, placeholder_ids)

        logger.info(f"[{block_id}] Pipeline complete. {len(claims)} claims added to pending.")

    except Exception:
        logger.exception(f"[{block_id}] Pipeline error")


# =============================================================================
# Pending Claims Management
# =============================================================================

@router.get('/pending-claims')
async def get_pending_claims(episode: str | None = None):
    """Return pending claim blocks (newest first), optionally filtered by episode"""
    db = state.get_db()
    return await db.get_pending_blocks(episode_key=episode)


@router.post('/pending-claims', status_code=201, response_model=ProcessingResponse)
async def receive_pending_claims(request: PendingClaimsRequest):
    """Receive pending claims (for manual testing or external sources)"""
    block_id = request.block_id or f"block_{int(datetime.now().timestamp() * 1000)}"
    timestamp = request.timestamp or datetime.now().isoformat()
    claims = request.claims
    episode_key = request.episode_key or state.current_episode_key

    # Ensure unique block_id
    db = state.get_db()
    counter = 1
    base_id = block_id
    while await db.block_id_exists(block_id):
        block_id = f"{base_id}_{counter}"
        counter += 1

    pending_block = {
        "block_id": block_id,
        "timestamp": timestamp,
        "claims_count": len(claims),
        "claims": claims,
        "status": "pending",
        "episode_key": episode_key
    }

    await db.add_pending_block(pending_block)

    logger.info(f"Pending claims received: {block_id} with {len(claims)} claims")

    return ProcessingResponse(
        status="success",
        block_id=block_id,
        claims_count=len(claims)
    )


@router.delete('/pending-claims/{block_id}')
async def dismiss_pending_block(block_id: str):
    """Delete a pending block (after claims have been staged/discarded/sent)."""
    db = state.get_db()
    deleted = await db.delete_pending_block(block_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Block not found")
    return {"status": "deleted", "block_id": block_id}


@router.post('/approve-claims', status_code=202, response_model=ProcessingResponse)
async def approve_claims(
    request: ClaimApprovalRequest,
):
    """
    Approve selected claims and start fact-checking.

    Uses local FactChecker service.
    """
    if not request.claims:
        raise HTTPException(status_code=400, detail="No claims selected")

    episode_key = request.episode_key or state.current_episode_key
    logger.info(f"Approving {len(request.claims)} claims from block {request.block_id}")

    # Use thematic context from episode config, or headline from text blocks
    db = state.get_db()
    context = None
    ep = EPISODES.get(episode_key)
    if ep:
        context = ep.context
    elif request.block_id:
        block = await db.get_pending_block_by_id(request.block_id)
        if block:
            context = block.get("headline", "")

    # Insert placeholder fact-checks immediately so users see them while research runs
    now = datetime.now().isoformat()
    placeholder_ids = []
    for claim in request.claims:
        placeholder = {
            "sprecher": claim.get("name", ""),
            "behauptung": claim.get("claim", ""),
            "consistency": "",
            "begruendung": "",
            "quellen": [],
            "timestamp": now,
            "episode_key": episode_key,
            "status": "processing",
        }
        pid = await db.add_fact_check(placeholder)
        placeholder_ids.append(pid)

    # Enqueue for processing (queue worker respects max_concurrency)
    await state.claim_queue.put((request.claims, episode_key, context, placeholder_ids))

    return ProcessingResponse(
        status="processing",
        message=f"{len(request.claims)} claims submitted for fact-checking",
        claims_count=len(request.claims)
    )


async def _mark_placeholder_error(db, pid: int, message: str = "Fehler bei der Recherche"):
    """Mark a processing placeholder as error if it's still in processing state."""
    existing = await db.get_fact_check_by_id(pid)
    if existing and existing.get("status") == "processing":
        await db.update_fact_check(pid, {
            "consistency": "",
            "begruendung": message,
            "quellen": [],
            "status": "error",
        })


async def process_fact_checks_async(claims: list, episode_key: str, context: str = None, placeholder_ids: list = None):
    """
    Background task: fact-check claims using FactChecker service.
    Updates placeholder rows (inserted by approve_claims) in place.
    """
    try:
        logger.info(f"Starting fact-check for {len(claims)} claims...")

        fact_checker = get_fact_checker()
        episode_date = EPISODES[episode_key].date if episode_key in EPISODES else None

        # Use async method if available, otherwise wrap sync call
        if hasattr(fact_checker, 'check_claims_async'):
            results = await fact_checker.check_claims_async(claims, context=context, episode_date=episode_date)
        else:
            results = await asyncio.to_thread(fact_checker.check_claims, claims, context=context, episode_date=episode_date)

        # Store results: update placeholders in place, or insert new rows
        db = state.get_db()
        for i, result in enumerate(results):
            fact_check = build_fact_check_dict(to_dict(result), episode_key)
            if placeholder_ids and i < len(placeholder_ids):
                await db.update_fact_check(placeholder_ids[i], fact_check)
                logger.info(f"Fact-check updated (placeholder {placeholder_ids[i]}): {fact_check['sprecher']} - {fact_check['consistency']}")
            else:
                await db.add_fact_check(fact_check)
                logger.info(f"Fact-check complete: {fact_check['sprecher']} - {fact_check['consistency']}")

        # Mark remaining placeholders as error if fewer results than expected
        if placeholder_ids:
            for j in range(len(results), len(placeholder_ids)):
                await _mark_placeholder_error(db, placeholder_ids[j], "Kein Ergebnis erhalten")
                logger.warning(f"Placeholder {placeholder_ids[j]} had no result, marked as error")

        logger.info(f"Fact-checking complete. {len(results)} results stored.")

    except Exception:
        logger.exception("Error in fact-check processing")
        # Clean up any remaining processing placeholders
        if placeholder_ids:
            db = state.get_db()
            for pid in placeholder_ids:
                await _mark_placeholder_error(db, pid)


async def claim_queue_worker(max_concurrency: int = 2):
    """
    Queue worker: processes claim batches from state.claim_queue.

    Runs max_concurrency batches concurrently. Further batches wait in queue
    instead of firing immediately, preventing API overload on large approvals.
    """
    semaphore = asyncio.Semaphore(max_concurrency)
    logger.info(f"Claim queue worker started (max_concurrency={max_concurrency})")

    async def run_batch(claims, episode_key, context, placeholder_ids):
        async with semaphore:
            await process_fact_checks_async(claims, episode_key, context, placeholder_ids)

    while True:
        item = await state.claim_queue.get()
        claims, episode_key, context, placeholder_ids = item

        async def _batch_and_done(c, ek, ctx, pids):
            try:
                await run_batch(c, ek, ctx, pids)
            finally:
                state.claim_queue.task_done()

        asyncio.create_task(_batch_and_done(claims, episode_key, context, placeholder_ids))
