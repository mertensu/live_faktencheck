"""
Fact-Check Backend API

FastAPI server that handles:
- Live streaming lane (/api/stream: transcription, claim gate, fast fact-check)
- Fact-check storage and sessions
- Episode configuration
"""

import os
import logging
from contextlib import asynccontextmanager

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

    yield

    # Shutdown: close database
    logger.info("FastAPI server shutting down...")
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
