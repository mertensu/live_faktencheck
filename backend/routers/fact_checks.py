"""
Fact-check storage endpoints.

Handles CRUD operations for fact-check results.
"""

import json
import asyncio
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, Query

from backend.models import (
    FactCheckRequest,
    ClaimUpdateRequest,
    ProcessingResponse,
    FactCheckStoredResponse,
)
from backend.state import to_dict
from backend.services.registry import get_fact_checker
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["fact-checks"])


@router.get('/fact-checks')
async def get_fact_checks(episode: Optional[str] = Query(default=None)):
    """Return fact-checks, optionally filtered by episode"""
    db = state.get_db()
    return await db.get_fact_checks(episode_key=episode)


@router.post('/fact-checks', status_code=201, response_model=FactCheckStoredResponse)
async def receive_fact_check(request: FactCheckRequest):
    """Receive fact-check results (for manual testing or external sources)"""
    # Support both German and English field names
    sprecher = request.sprecher or request.speaker or ""
    behauptung = request.behauptung or request.original_claim or request.claim or ""
    consistency = request.consistency or request.urteil or ""
    begruendung = request.begruendung or request.evidence or ""
    quellen = request.quellen or request.sources or []
    episode_key = request.episode_key or request.episode or state.current_episode_key

    # Handle string sources
    if isinstance(quellen, str):
        try:
            quellen = json.loads(quellen)
        except (json.JSONDecodeError, ValueError):
            quellen = [quellen] if quellen else []

    db = state.get_db()
    fact_check = {
        "sprecher": sprecher,
        "behauptung": behauptung,
        "consistency": consistency,
        "begruendung": begruendung,
        "quellen": quellen if isinstance(quellen, list) else [],
        "timestamp": datetime.now().isoformat(),
        "episode_key": episode_key
    }
    fact_check_id = await db.add_fact_check(fact_check)

    logger.info(f"Fact-check stored: ID {fact_check_id} - {sprecher} - {consistency}")

    return FactCheckStoredResponse(status="success", id=fact_check_id)


@router.put('/fact-checks/{fact_check_id}', status_code=202, response_model=ProcessingResponse)
async def update_fact_check(
    fact_check_id: int,
    request: ClaimUpdateRequest,
    background_tasks: BackgroundTasks
):
    """
    Re-run fact-check for an existing claim (overwrite result).

    Finds existing fact-check by ID, re-runs fact-checker with updated claim,
    and replaces the result in the fact_checks list.
    """
    # Find existing fact-check
    db = state.get_db()
    existing = await db.get_fact_check_by_id(fact_check_id)

    if not existing:
        raise HTTPException(status_code=404, detail=f"Fact-check {fact_check_id} not found")

    episode_key = request.episode_key or existing.get("episode_key") or state.current_episode_key

    logger.info(f"Re-running fact-check for ID {fact_check_id}: {request.name} - {request.claim[:50]}...")

    # Start fact-checking in background
    background_tasks.add_task(
        process_fact_check_update_async,
        fact_check_id,
        request.name,
        request.claim,
        episode_key
    )

    return ProcessingResponse(
        status="processing",
        message=f"Fact-check {fact_check_id} re-run started"
    )


@router.post('/fact-checks/resend', status_code=202, response_model=ProcessingResponse)
async def resend_fact_check(
    request: ClaimUpdateRequest,
    background_tasks: BackgroundTasks
):
    """
    Re-run fact-check by matching speaker+claim text.

    Finds existing fact-check by speaker and claim text, re-runs fact-checker,
    and replaces the result. If no match found, creates a new fact-check.
    """
    # Find existing fact-check: by ID first, then by speaker+original_claim, then by speaker+claim
    db = state.get_db()
    existing = None
    existing_id = None
    if request.fact_check_id:
        existing = await db.get_fact_check_by_id(request.fact_check_id)
        if existing:
            existing_id = existing["id"]
    if not existing and request.original_claim:
        existing = await db.find_fact_check(request.name, request.original_claim)
        if existing:
            existing_id = existing["id"]
    if not existing:
        existing = await db.find_fact_check(request.name, request.claim)
        if existing:
            existing_id = existing["id"]

    episode_key = request.episode_key or (existing.get("episode_key") if existing else None) or state.current_episode_key

    if existing:
        logger.info(f"Re-sending fact-check (matched ID {existing_id}): {request.name} - {request.claim[:50]}...")
        background_tasks.add_task(
            process_fact_check_update_async,
            existing_id,
            request.name,
            request.claim,
            episode_key
        )
        return ProcessingResponse(
            status="processing",
            message=f"Fact-check {existing_id} re-run started (matched by speaker+claim)"
        )
    else:
        # No match - create new fact-check
        logger.info(f"No existing fact-check found, creating new: {request.name} - {request.claim[:50]}...")
        background_tasks.add_task(
            process_new_fact_check_async,
            request.name,
            request.claim,
            episode_key
        )
        return ProcessingResponse(
            status="processing",
            message="New fact-check started (no existing match found)"
        )


async def process_new_fact_check_async(name: str, claim: str, episode_key: str):
    """
    Background task: create a new fact-check.
    """
    try:
        logger.info(f"Creating new fact-check: {name} - {claim[:50]}...")

        fact_checker = get_fact_checker()
        claims_to_check = [{"name": name, "claim": claim}]

        if hasattr(fact_checker, 'check_claims_async'):
            results = await fact_checker.check_claims_async(claims_to_check)
        else:
            results = await asyncio.to_thread(fact_checker.check_claims, claims_to_check)

        if not results:
            logger.error("No results from fact-checker for new claim")
            return

        result = results[0]
        result_dict = to_dict(result)
        sources = result_dict.get("sources", [])

        db = state.get_db()
        fact_check = {
            "sprecher": result_dict.get("speaker", name),
            "behauptung": result_dict.get("original_claim", claim),
            "consistency": result_dict.get("consistency", "unklar"),
            "begruendung": result_dict.get("evidence", ""),
            "quellen": [to_dict(s) for s in sources] if sources else [],
            "timestamp": datetime.now().isoformat(),
            "episode_key": episode_key
        }
        new_id = await db.add_fact_check(fact_check)
        logger.info(f"New fact-check created: ID {new_id} - {fact_check['consistency']}")

    except Exception:
        logger.exception("Error creating new fact-check")


async def process_fact_check_update_async(fact_check_id: int, name: str, claim: str, episode_key: str):
    """
    Background task: re-run fact-check and update existing entry.
    """
    try:
        logger.info(f"Re-running fact-check for ID {fact_check_id}...")

        fact_checker = get_fact_checker()
        claims_to_check = [{"name": name, "claim": claim}]

        # Use async method if available, otherwise wrap sync call
        if hasattr(fact_checker, 'check_claims_async'):
            results = await fact_checker.check_claims_async(claims_to_check)
        else:
            results = await asyncio.to_thread(fact_checker.check_claims, claims_to_check)

        if not results:
            logger.error(f"No results from fact-checker for ID {fact_check_id}")
            return

        result = results[0]
        result_dict = to_dict(result)
        sources = result_dict.get("sources", [])

        # Update existing fact-check
        db = state.get_db()
        updated_data = {
            "sprecher": result_dict.get("speaker", name),
            "behauptung": result_dict.get("original_claim", claim),
            "consistency": result_dict.get("consistency", "unklar"),
            "begruendung": result_dict.get("evidence", ""),
            "quellen": [to_dict(s) for s in sources] if sources else [],
            "timestamp": datetime.now().isoformat(),
            "episode_key": episode_key
        }
        await db.update_fact_check(fact_check_id, updated_data)
        logger.info(f"Fact-check {fact_check_id} updated: {updated_data['consistency']}")

        logger.info(f"Fact-check {fact_check_id} re-run complete.")

    except Exception:
        logger.exception(f"Error re-running fact-check {fact_check_id}")
