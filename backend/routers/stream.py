"""
Live streaming WebSocket endpoint (SG-4).

The browser opens a WebSocket, sends 16 kHz mono PCM16 audio as binary frames, and
receives JSON status events (partial transcript, claim processing/result). The backend
relays audio to AssemblyAI Universal-Streaming and drives the fast lane via
``StreamingSession``.

Auth: header-based ``require_code`` can't run on a WS handshake, so the access code is
passed as a query param and validated here against the same ``codes`` table. Audio
budget is metered by connection wall-clock, mirroring the block pipeline.
"""

import os
import time
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.config import Episode
from backend.services.registry import get_claim_extractor, get_fast_fact_checker
from backend.services.gate import ExtractorGate
from backend.services.streaming import StreamingSession
import backend.state as state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["stream"])

# WebSocket close codes (RFC 6455 + app-specific 4xxx range).
WS_POLICY_VIOLATION = 1008
WS_TRY_AGAIN_LATER = 1013


@router.websocket("/api/stream")
async def stream(websocket: WebSocket):
    session_id = websocket.query_params.get("session_id")
    code_str = websocket.query_params.get("code")

    db = state.get_db()

    # --- auth (pre-accept) ---------------------------------------------------
    code = await db.get_code(code_str) if code_str else None
    if code is None:
        await websocket.close(code=WS_POLICY_VIOLATION, reason="Zugangscode ungültig")
        return
    if not session_id:
        await websocket.close(code=WS_POLICY_VIOLATION, reason="session_id erforderlich")
        return

    # --- budget guard --------------------------------------------------------
    limit = code.get("audio_seconds_limit")
    used = code.get("audio_seconds_used", 0)
    if limit is not None and used >= limit:
        await websocket.close(code=WS_TRY_AGAIN_LATER, reason="Audio-Kontingent aufgebraucht")
        return

    api_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not api_key:
        await websocket.close(code=WS_TRY_AGAIN_LATER, reason="Streaming nicht konfiguriert")
        return

    await websocket.accept()

    # --- load episode context ------------------------------------------------
    session_row = await db.get_session(session_id)
    ep = Episode.from_session_row(session_row) if session_row else None
    episode_date = session_row["date"] if session_row else None

    async def on_event(event: dict) -> None:
        try:
            await websocket.send_json(event)
        except Exception:
            pass  # client gone; the receive loop will exit and clean up

    session = StreamingSession(
        session_id,
        ExtractorGate(get_claim_extractor()),
        get_fast_fact_checker(),
        db,
        guests=ep.guests if ep else [],
        context=ep.context if ep else "",
        conversation_type=ep.conversation_type if ep else "debate",
        excluded_speakers=ep.excluded_speakers if ep else [],
        episode_date=episode_date,
        on_event=on_event,
    )
    state.streaming_sessions[session_id] = session
    started = time.monotonic()

    try:
        await session.start(api_key)
        await on_event({"type": "ready", "session_id": session_id})
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break
            data = message.get("bytes")
            if data:
                await session.feed(data)
                continue
            text = message.get("text")
            if text == "stop":
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception(f"[stream:{session_id}] error")
    finally:
        await session.stop()
        state.streaming_sessions.pop(session_id, None)
        # Meter the real connection duration against the code's budget.
        elapsed = int(round(time.monotonic() - started))
        if elapsed > 0:
            try:
                await db.increment_audio_seconds(code["code"], elapsed)
            except Exception:
                logger.exception("Failed to meter streaming audio seconds")
        try:
            await websocket.close()
        except Exception:
            pass
