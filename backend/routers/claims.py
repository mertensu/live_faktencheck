"""
Claims management endpoints.

Handles pending claims and text-based claim extraction.
"""

import asyncio
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, BackgroundTasks

from backend.models import (
    TextBlockRequest,
    ClaimApprovalRequest,
    PendingClaimsRequest,
    ProcessingResponse,
)
from backend.state import (
    fact_checks,
    pending_claims_blocks,
    processing_lock,
    to_dict,
)
import backend.state as state

from backend.show_config import get_info
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

        # Claim extraction (using article-specific prompt)
        logger.info(f"[{block_id}] Extracting claims from article...")
        claim_extractor = get_claim_extractor()

        # Use async method if available, otherwise wrap sync call
        if hasattr(claim_extractor, 'extract_from_article_async'):
            claims = await claim_extractor.extract_from_article_async(text, headline, publication_date)
        else:
            claims = await asyncio.to_thread(
                claim_extractor.extract_from_article, text, headline, publication_date
            )
        logger.info(f"[{block_id}] Extracted {len(claims)} claims")

        if not claims:
            logger.info(f"[{block_id}] No claims extracted, skipping")
            return

        # Store as pending claims
        async with processing_lock:
            pending_block = {
                "block_id": block_id,
                "timestamp": datetime.now().isoformat(),
                "claims_count": len(claims),
                "claims": [to_dict(c) for c in claims],
                "status": "pending",
                "source_id": source_id,
                "episode_key": state.current_episode_key or "test",
                "headline": headline,
                "text_preview": text[:200] + "..." if len(text) > 200 else text
            }
            pending_claims_blocks.append(pending_block)

        logger.info(f"[{block_id}] Pipeline complete. {len(claims)} claims added to pending.")

    except Exception:
        logger.exception(f"[{block_id}] Pipeline error")


# =============================================================================
# Pending Claims Management
# =============================================================================

@router.get('/pending-claims')
async def get_pending_claims():
    """Return all pending claim blocks (newest first)"""
    sorted_blocks = sorted(
        pending_claims_blocks,
        key=lambda x: x.get("timestamp", ""),
        reverse=True
    )
    return sorted_blocks


@router.post('/pending-claims', status_code=201, response_model=ProcessingResponse)
async def receive_pending_claims(request: PendingClaimsRequest):
    """Receive pending claims (for manual testing or external sources)"""
    block_id = request.block_id or f"block_{int(datetime.now().timestamp() * 1000)}"
    timestamp = request.timestamp or datetime.now().isoformat()
    claims = request.claims
    episode_key = request.episode_key or state.current_episode_key

    # Ensure unique block_id
    existing_ids = [b.get("block_id") for b in pending_claims_blocks]
    if block_id in existing_ids:
        counter = 1
        base_id = block_id
        while block_id in existing_ids:
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

    async with processing_lock:
        pending_claims_blocks.append(pending_block)

    logger.info(f"Pending claims received: {block_id} with {len(claims)} claims")

    return ProcessingResponse(
        status="success",
        block_id=block_id,
        claims_count=len(claims)
    )


@router.post('/approve-claims', status_code=202, response_model=ProcessingResponse)
async def approve_claims(
    request: ClaimApprovalRequest,
    background_tasks: BackgroundTasks
):
    """
    Approve selected claims and start fact-checking.

    Uses local FactChecker service.
    """
    if not request.claims:
        raise HTTPException(status_code=400, detail="No claims selected")

    episode_key = request.episode_key or state.current_episode_key
    logger.info(f"Approving {len(request.claims)} claims from block {request.block_id}")

    # Try to find context from the pending block, fall back to config
    context = None
    if request.block_id:
        for b in pending_claims_blocks:
            if b.get("block_id") == request.block_id:
                context = b.get("info") or b.get("headline")
                break

    # Fall back to config info if no context found in pending block
    if not context:
        context = get_info(episode_key)
        if context:
            logger.info(f"Using context from config for episode {episode_key}")

    # Start fact-checking in background
    background_tasks.add_task(process_fact_checks_async, request.claims, episode_key, context)

    return ProcessingResponse(
        status="processing",
        message=f"{len(request.claims)} claims submitted for fact-checking",
        claims_count=len(request.claims)
    )


async def process_fact_checks_async(claims: list, episode_key: str, context: str = None):
    """
    Background task: fact-check claims using FactChecker service.
    """
    try:
        logger.info(f"Starting fact-check for {len(claims)} claims...")

        fact_checker = get_fact_checker()

        # Use async method if available, otherwise wrap sync call
        if hasattr(fact_checker, 'check_claims_async'):
            results = await fact_checker.check_claims_async(claims, context=context)
        else:
            results = await asyncio.to_thread(fact_checker.check_claims, claims, context=context)

        # Store results
        async with processing_lock:
            for result in results:
                result_dict = to_dict(result)
                sources = result_dict.get("sources", [])

                fact_check = {
                    "id": state.allocate_fact_check_id(),
                    "sprecher": result_dict.get("speaker", ""),
                    "behauptung": result_dict.get("original_claim", ""),
                    "consistency": result_dict.get("consistency", "unklar"),
                    "begruendung": result_dict.get("evidence", ""),
                    "quellen": [to_dict(s) for s in sources] if sources else [],
                    "timestamp": datetime.now().isoformat(),
                    "episode_key": episode_key
                }
                fact_checks.append(fact_check)
                logger.info(f"Fact-check complete: {fact_check['sprecher']} - {fact_check['consistency']}")

        logger.info(f"Fact-checking complete. {len(results)} results stored.")

    except Exception:
        logger.exception("Error in fact-check processing")
