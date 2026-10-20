"""
Fact-check storage endpoints.

Handles CRUD operations for fact-check results.
"""

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.auth import require_code
from backend.models import DiscardRequest, FactCheckRequest, FactCheckStoredResponse
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["fact-checks"])


@router.get('/fact-checks')
async def get_fact_checks(session_id: Optional[str] = Query(default=None), status: Optional[str] = Query(default=None)):
    """Return fact-checks for a single session.

    A non-empty ``session_id`` scope is required: without it the query would
    return every session's fact-checks, leaking results across users. Callers
    must always pass the session they own/are viewing.
    """
    if not session_id or not session_id.strip():
        raise HTTPException(status_code=400, detail="session_id ist erforderlich")
    db = state.get_db()
    return await db.get_fact_checks(session_id=session_id, status=status)


@router.post('/fact-checks', status_code=201, response_model=FactCheckStoredResponse)
async def receive_fact_check(request: FactCheckRequest):
    """Receive fact-check results (for manual testing or external sources)"""
    # Support both German and English field names
    sprecher = request.sprecher or request.speaker or ""
    behauptung = request.behauptung or request.original_claim or request.claim or ""
    consistency = request.consistency or request.urteil or ""
    begruendung = request.begruendung or request.evidence or ""
    quellen = request.quellen or request.sources or []
    session_id = request.session_id

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
        "session_id": session_id
    }
    fact_check_id = await db.add_fact_check(fact_check)

    logger.info(f"Fact-check stored: ID {fact_check_id} - {sprecher} - {consistency}")

    return FactCheckStoredResponse(status="success", id=fact_check_id)


async def _owned_fact_check(fact_check_id: int, code: dict) -> dict:
    """The fact-check, if the caller's code owns its session.

    The API is publicly reachable and IDs are sequential, so any valid code could
    otherwise walk the range and touch other people's results. A fact-check outside
    the caller's sessions answers 404, the same as a missing one.
    """
    db = state.get_db()
    fc = await db.get_fact_check_by_id(fact_check_id)
    session = await db.get_session(fc["session_id"]) if fc and fc["session_id"] else None
    if session is None or session["owner_code"] != code["code"]:
        raise HTTPException(status_code=404, detail=f"Fact-check {fact_check_id} not found")
    return fc


@router.delete('/fact-checks/{fact_check_id}')
async def delete_fact_check(
    fact_check_id: int,
    code: dict = Depends(require_code),
):
    """Permanently delete a fact-check by ID — only with the code that owns its session."""
    await _owned_fact_check(fact_check_id, code)
    await state.get_db().delete_fact_check(fact_check_id)
    logger.info(f"Fact-check {fact_check_id} deleted")
    return {"status": "deleted", "id": fact_check_id}


@router.post('/fact-checks/{fact_check_id}/discard')
async def discard_fact_check(
    fact_check_id: int,
    request: DiscardRequest,
    code: dict = Depends(require_code),
):
    """Hide a fact-check from every view ("Verwerfen"), or bring it back. The row stays,
    so a discard can be undone and reviewed. A live session is told too, so that a later
    speaker change neither re-publishes nor deletes the claim."""
    fc = await _owned_fact_check(fact_check_id, code)
    await state.get_db().set_discarded(fact_check_id, request.discarded)
    for session in list(state.streaming_sessions.values()):
        if getattr(session, "session_id", None) == fc["session_id"]:
            session.set_discarded(fact_check_id, request.discarded)
    logger.info(f"Fact-check {fact_check_id} {'discarded' if request.discarded else 'restored'}")
    return {"status": "discarded" if request.discarded else "restored", "id": fact_check_id}
