"""
Fact-Check Backend API

FastAPI server that handles:
- Live streaming lane (/api/stream: transcription, claim gate, fast fact-check)
- Fact-check storage and sessions
- Episode configuration
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from backend.routers import fact_checks, config, sessions, stream
from backend.auth import seed_codes_from_env
from backend.database import Database
from backend import state
from backend.services.observability import configure_logfire
from backend.config import EPISODES, episode_to_session_dict

# Load environment variables
load_dotenv()

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Stored live transcripts are deleted this many days after they were spoken (privacy
# policy, section 5). Checked at startup and then every TRANSCRIPT_PURGE_INTERVAL_S.
TRANSCRIPT_RETENTION_DAYS = int(os.getenv("TRANSCRIPT_RETENTION_DAYS", "30"))
TRANSCRIPT_PURGE_INTERVAL_S = 6 * 3600


async def purge_transcripts(db) -> None:
    """Delete transcript turns past the retention window; never raises."""
    try:
        deleted = await db.purge_transcripts(TRANSCRIPT_RETENTION_DAYS)
        if deleted:
            logger.info(f"Purged {deleted} transcript turn(s) older than {TRANSCRIPT_RETENTION_DAYS} days")
    except Exception:
        logger.exception("Transcript purge failed")


async def purge_transcripts_periodically(db, interval_s: float = TRANSCRIPT_PURGE_INTERVAL_S) -> None:
    while True:
        await asyncio.sleep(interval_s)
        await purge_transcripts(db)


async def seed_legacy_episodes(db) -> None:
    """Seed hardcoded EPISODES into the sessions table (idempotent)."""
    for ep in EPISODES.values():
        await db.seed_session_if_absent(episode_to_session_dict(ep))


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: configure observability (no-op without LOGFIRE_TOKEN)
    configure_logfire()

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
    await seed_legacy_episodes(db)
    logger.info("Legacy episodes seeded into sessions table")

    # Startup: seed access codes from ACCESS_CODES env (fail-closed if unset)
    seeded = await seed_codes_from_env(db)
    if seeded:
        logger.info(f"Seeded {seeded} access code(s) from ACCESS_CODES")
    elif await db.count_codes() == 0:
        logger.warning(
            "No access codes configured (ACCESS_CODES unset) — gated endpoints "
            "will reject all requests until codes are seeded."
        )

    # Startup: transcript retention — once now, then periodically while running
    await purge_transcripts(db)
    purge_task = asyncio.create_task(purge_transcripts_periodically(db))

    yield

    # Shutdown: stop the purge task, close database
    logger.info("FastAPI server shutting down...")
    purge_task.cancel()
    with suppress(asyncio.CancelledError):
        await purge_task
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
    # Cloudflare Workers preview deployments (per-branch/per-deploy subdomains of the form
    # <hash>-live-faktencheck.mertens-ulf.workers.dev) — lets a branch preview build call
    # the live API before merging to main.
    allow_origin_regex=r"https://[a-z0-9-]+-live-faktencheck\.mertens-ulf\.workers\.dev",
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "X-Access-Code"],
)

# Include routers
app.include_router(fact_checks.router)
app.include_router(config.router)
app.include_router(sessions.router)
app.include_router(stream.router)


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
|    WS   /api/stream          - Live audio stream             |
|    POST /api/sessions        - Create a session              |
|    GET  /api/fact-checks     - Get completed fact-checks     |
|    GET  /api/health          - Health check                  |
+==============================================================+
    """)

    uvicorn.run("backend.app:app", host="0.0.0.0", port=port, reload=True)
