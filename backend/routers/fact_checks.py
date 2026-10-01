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
from backend.models import FactCheckRequest, FactCheckStoredResponse
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


@router.delete('/fact-checks/{fact_check_id}')
async def delete_fact_check(
    fact_check_id: int,
    code: dict = Depends(require_code),
):
    """Permanently delete a fact-check by ID — only with the code that owns its session.

    The API is publicly reachable and IDs are sequential, so any valid code could
    otherwise walk the range and erase other people's results. A fact-check outside
    the caller's sessions answers 404, the same as a missing one.
    """
    db = state.get_db()
    fc = await db.get_fact_check_by_id(fact_check_id)
    session = await db.get_session(fc["session_id"]) if fc and fc["session_id"] else None
    if session is None or session["owner_code"] != code["code"]:
        raise HTTPException(status_code=404, detail=f"Fact-check {fact_check_id} not found")
    await db.delete_fact_check(fact_check_id)
    logger.info(f"Fact-check {fact_check_id} deleted")
    return {"status": "deleted", "id": fact_check_id}

