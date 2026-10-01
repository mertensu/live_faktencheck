"""Session management endpoints."""
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import require_code
from backend.models import CreateSessionRequest, MySessionSummary, SessionResponse
from backend.services.transcription import clean_keyterms
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
        "type": request.type,
        "conversation_type": request.conversation_type,
        "excluded_speakers": request.excluded_speakers,
        "keyterms": clean_keyterms(request.keyterms),
        "auto_check": request.auto_check,
        "status": "active",
        "visibility": "private",
        "owner_code": code["code"],
        "created_at": datetime.now().isoformat(),
    }
    await db.add_session(row)
    logger.info(f"Session created: {session_id} ({request.title})")
    return SessionResponse(**await db.get_session(session_id))


@router.get("/my/sessions", response_model=list[MySessionSummary])
async def my_sessions(code: dict = Depends(require_code)):
    """ "Meine Checks": the sessions created with the caller's access code."""
    return await state.get_db().list_sessions_by_owner(code["code"])


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    db = state.get_db()
    s = await db.get_session(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    return SessionResponse(**s)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, code: dict = Depends(require_code)):
    """Permanently delete a session and its fact-checks — only with the code that
    created it. Someone else's session answers 404, so its existence isn't revealed;
    legacy seeded sessions have no owner and can't be deleted here."""
    db = state.get_db()
    s = await db.get_session(session_id)
    if s is None or s["owner_code"] != code["code"]:
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    if session_id in state.streaming_sessions:
        raise HTTPException(status_code=409, detail="Live-Check läuft noch — erst stoppen, dann löschen")
    await db.delete_session(session_id)
    logger.info(f"Session deleted by owner: {session_id}")
    return {"status": "deleted", "session_id": session_id}


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: str):
    db = state.get_db()
    if not await db.end_session(session_id):
        raise HTTPException(status_code=404, detail=f"Unknown session: {session_id}")
    return {"status": "ended", "session_id": session_id}

