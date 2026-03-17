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
from backend.services.reference_fetcher import fetch_show_background
from backend.services.vector_store import create_search_tool

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
            ep_key = pending_block["episode_key"]
            ep_cfg = EPISODES.get(ep_key)
            text_reference_links = ep_cfg.reference_links if ep_cfg else []
            text_show_bg = await fetch_show_background(text_reference_links)
            text_doc_tool = create_search_tool(ep_key, ep_cfg.reference_pdfs if ep_cfg else None) if ep_key else None
            await process_fact_checks_async(selected, ep_key, headline, placeholder_ids, text_show_bg, text_doc_tool)

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
    db = state.get_db()
    context = None
    if request.block_id:
        block = await db.get_pending_block_by_id(request.block_id)
        if block:
            context = block.get("info") or block.get("headline")

    # Fall back to config info if no context found in pending block
    if not context:
        ep = EPISODES.get(episode_key)
        if ep:
            context = ep.info
            logger.info(f"Using context from config for episode {episode_key}")

    # Load reference links and pre-fetch as show background
    ep = EPISODES.get(episode_key)
    reference_links = ep.reference_links if ep else []
    show_background = await fetch_show_background(reference_links)

    # Load local document search tool if a FAISS index exists for this episode
    document_tool = create_search_tool(episode_key, ep.reference_pdfs if ep else None) if episode_key else None
    if document_tool:
        logger.info(f"Loaded document search tool for episode {episode_key}")

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

    # Start fact-checking in background, passing placeholder IDs for in-place update
    background_tasks.add_task(process_fact_checks_async, request.claims, episode_key, context, placeholder_ids, show_background, document_tool)

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


async def process_fact_checks_async(claims: list, episode_key: str, context: str = None, placeholder_ids: list = None, show_background: str = None, document_tool=None):
    """
    Background task: fact-check claims using FactChecker service.
    Updates placeholder rows (inserted by approve_claims) in place.
    """
    try:
        logger.info(f"Starting fact-check for {len(claims)} claims...")

        fact_checker = get_fact_checker()
        extra_tools = [document_tool] if document_tool else []

        # Use async method if available, otherwise wrap sync call
        if hasattr(fact_checker, 'check_claims_async'):
            results = await fact_checker.check_claims_async(claims, context=context, show_background=show_background, extra_tools=extra_tools)
        else:
            results = await asyncio.to_thread(fact_checker.check_claims, claims, context=context, show_background=show_background, extra_tools=extra_tools)

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
