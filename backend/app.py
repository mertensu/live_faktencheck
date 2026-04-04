"""
Fact-Check Backend API

FastAPI server that handles:
- Audio block processing (transcription + claim extraction)
- Pending claims management
- Fact-check processing and storage
- Episode configuration
"""

import os
import shutil
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

import asyncio

from backend.routers import audio, claims, fact_checks, config, pipeline
from backend.routers.audio import AUDIO_TMP_DIR
from backend.routers.claims import claim_queue_worker
from backend.database import Database
from backend import state

# Load environment variables
load_dotenv()

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: clear orphaned temp audio files from previous crash
    shutil.rmtree(AUDIO_TMP_DIR, ignore_errors=True)
    os.makedirs(AUDIO_TMP_DIR, exist_ok=True)
    logger.info(f"Cleared temp audio dir: {AUDIO_TMP_DIR}")

    # Startup: initialize database
    logger.info("FastAPI server starting up...")
    db_mode = os.getenv("DB_MODE", "file")
    if db_mode == "memory":
        logger.info("Using in-memory database (no persistence)")
        db = Database(":memory:")
    else:
        db = Database()
        logger.info(f"Using file database: {db.db_path}")
    await db.connect()
    state.db = db

    # Startup: start claim queue worker
    max_concurrency = int(os.getenv("FACT_CHECK_MAX_CONCURRENCY", "2"))
    state.queue_worker_task = asyncio.create_task(claim_queue_worker(max_concurrency))
    logger.info("Claim queue worker started")

    yield

    # Shutdown: cancel queue worker and close database
    logger.info("FastAPI server shutting down...")
    if state.queue_worker_task:
        state.queue_worker_task.cancel()
        try:
            await state.queue_worker_task
        except asyncio.CancelledError:
            pass
    await db.close()
    state.db = None


# FastAPI app
app = FastAPI(
    title="Fact-Check Backend",
    description="Live fact-checking application for German TV shows",
    version="2.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://live-faktencheck.de",
        "https://www.live-faktencheck.de",
        "https://live-faktencheck.mertens-ulf.workers.dev",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
)

# Include routers
app.include_router(audio.router)
app.include_router(claims.router)
app.include_router(fact_checks.router)
app.include_router(config.router)
app.include_router(pipeline.router)


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv("PORT", 5000))

    print(f"""
+==============================================================+
|  Fact-Check Backend (FastAPI)                                |
+==============================================================+
|  Server:     http://0.0.0.0:{port}                            |
|  API Docs:   http://0.0.0.0:{port}/docs                       |
|                                                              |
|  Endpoints:                                                  |
|    POST /api/audio-block     - Receive audio from listener   |
|    POST /api/text-block      - Receive text from reader      |
|    GET  /api/pending-claims  - Get pending claims            |
|    POST /api/approve-claims  - Approve claims for checking   |
|    GET  /api/fact-checks     - Get completed fact-checks     |
|    PUT  /api/fact-checks/id  - Re-run fact-check (overwrite) |
|    GET  /api/health          - Health check                  |
+==============================================================+
    """)

    uvicorn.run("backend.app:app", host="0.0.0.0", port=port, reload=True)
