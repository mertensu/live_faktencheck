"""Session management endpoints."""
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import require_code
from backend.models import AutoCheckRequest, CreateSessionRequest, SessionResponse
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sessions"])


@router.post("/sessions", status_code=201, response_model=SessionResponse)
async def create_session(request: CreateSessionRequest, code: dict = Depends(require_code)):
    db = state.get_db()
    session_id = uuid.uuid4().hex[:12]
    row = {
        "session_id": session_id,
        "title": request.title,
        "date": request.date,
        "guests": request.guests,
        "context": request.context,
        "reference_links": request.reference_links,
        "type": request.type,
        "conversation_type": request.conversation_type,
        "status": "active",
        "visibility": "private",
        "owner_code": code["code"],
        "created_at": datetime.now().isoformat(),
    }
    await db.add_session(row)
    logger.info(f"Session created: {session_id} ({request.title})")
    return SessionResponse(**await db.get_session(session_id))


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    db = state.get_db()
    s = await db.get_session(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    return SessionResponse(**s)


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: str):
    db = state.get_db()
    if not await db.end_session(session_id):
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    return {"status": "ended", "session_id": session_id}


@router.post("/sessions/{session_id}/auto-check", response_model=SessionResponse)
async def set_auto_check(
    session_id: str,
    request: AutoCheckRequest,
    code: dict = Depends(require_code),
):
    db = state.get_db()
    if not await db.set_session_auto_check(session_id, request.enabled):
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    logger.info(f"Session {session_id} auto_check set to {request.enabled}")
    return SessionResponse(**await db.get_session(session_id))
