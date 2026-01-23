"""
Fact-Check Backend API

FastAPI server that handles:
- Audio block processing (transcription + claim extraction)
- Pending claims management
- Fact-check processing and storage
- Episode configuration
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from backend.models import (
    TextBlockRequest,
    ClaimApprovalRequest,
    ClaimUpdateRequest,
    FactCheckRequest,
    PendingClaimsRequest,
    SetEpisodeRequest,
    ProcessingResponse,
    HealthResponse,
    ShowsResponse,
    EpisodesResponse,
    FactCheckStoredResponse,
)

# Load environment variables
load_dotenv()

# Configure logging
log_level = os.getenv("LOG_LEVEL", "INFO")
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add project root to path for config import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config import get_show_config, get_all_shows, get_episodes_for_show, get_info
except ImportError:
    logger.warning("config.py not found. Using default configuration.")
    def get_show_config(episode_key=None):
        return {"speakers": [], "info": "", "name": "Unknown", "description": ""}
    def get_all_shows():
        return []
    def get_episodes_for_show(show_key):
        return []
    def get_info(episode_key=None):
        return ""

# Import services (lazy loading to avoid import errors if env vars not set)
_transcription_service = None
_claim_extractor = None
_fact_checker = None

def get_transcription_service():
    global _transcription_service
    if _transcription_service is None:
        from backend.services.transcription import TranscriptionService
        _transcription_service = TranscriptionService()
    return _transcription_service

def get_claim_extractor():
    global _claim_extractor
    if _claim_extractor is None:
        from backend.services.claim_extraction import ClaimExtractor
        _claim_extractor = ClaimExtractor()
    return _claim_extractor

def get_fact_checker():
    global _fact_checker
    if _fact_checker is None:
        from backend.services.fact_checker import FactChecker
        _fact_checker = FactChecker()
    return _fact_checker


# Lifespan context manager for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize services if needed
    logger.info("FastAPI server starting up...")
    yield
    # Shutdown: cleanup if needed
    logger.info("FastAPI server shutting down...")


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
        "https://mertensu.github.io",
        "http://localhost:3000",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
)

# In-memory storage
fact_checks = []
pending_claims_blocks = []
current_episode_key = None
processing_lock = asyncio.Lock()


def to_dict(obj):
    """Convert Pydantic model to dict, or return as-is if already a dict."""
    return obj.model_dump() if hasattr(obj, "model_dump") else obj

# Path for JSON files (for GitHub Pages)
DATA_DIR = Path(__file__).parent.parent / "frontend" / "public" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Audio Processing Pipeline
# =============================================================================

@app.post('/api/audio-block', status_code=202, response_model=ProcessingResponse)
async def receive_audio_block(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    episode_key: Optional[str] = Form(default=None),
    info: Optional[str] = Form(default=None)
):
    """
    Receive audio block from listener.py and start processing pipeline.

    Expected: multipart form data with:
    - audio: WAV file
    - episode_key: Episode identifier
    - info: (optional) Context information override
    """
    global current_episode_key

    try:
        audio_data = await audio.read()
        ep_key = episode_key or current_episode_key or 'test'
        context_info = info or get_info(ep_key)

        logger.info(f"Received audio block: {len(audio_data)} bytes, episode: {ep_key}")

        # Start background processing
        background_tasks.add_task(process_audio_pipeline_async, audio_data, ep_key, context_info)

        return ProcessingResponse(
            status="processing",
            message="Audio received, processing started",
            episode_key=ep_key
        )

    except Exception as e:
        logger.error(f"Error receiving audio block: {e}")
        raise HTTPException(status_code=400, detail=str(e))


async def process_audio_pipeline_async(audio_data: bytes, episode_key: str, info: str):
    """
    Background pipeline: audio -> transcription -> claim extraction -> pending claims
    """
    block_id = f"block_{int(datetime.now().timestamp() * 1000)}"

    try:
        logger.info(f"[{block_id}] Starting audio processing pipeline...")

        # Step 1: Transcription (sync call wrapped for async)
        logger.info(f"[{block_id}] Step 1: Transcribing audio...")
        transcription_service = get_transcription_service()
        transcript = await asyncio.to_thread(transcription_service.transcribe, audio_data)
        logger.info(f"[{block_id}] Transcription complete: {len(transcript)} chars")

        # Step 2: Claim extraction (async)
        logger.info(f"[{block_id}] Step 2: Extracting claims...")
        claim_extractor = get_claim_extractor()
        # Use async method if available, otherwise wrap sync call
        if hasattr(claim_extractor, 'extract_async'):
            claims = await claim_extractor.extract_async(transcript, info)
        else:
            claims = await asyncio.to_thread(claim_extractor.extract, transcript, info)
        logger.info(f"[{block_id}] Extracted {len(claims)} claims")

        if not claims:
            logger.info(f"[{block_id}] No claims extracted, skipping")
            return

        # Step 3: Store as pending claims
        async with processing_lock:
            pending_block = {
                "block_id": block_id,
                "timestamp": datetime.now().isoformat(),
                "claims_count": len(claims),
                "claims": [to_dict(c) for c in claims],
                "status": "pending",
                "episode_key": episode_key,
                "info": info,
                "transcript_preview": transcript[:200] + "..." if len(transcript) > 200 else transcript
            }
            pending_claims_blocks.append(pending_block)

        logger.info(f"[{block_id}] Pipeline complete. {len(claims)} claims added to pending.")

    except Exception as e:
        logger.error(f"[{block_id}] Pipeline error: {e}")
        import traceback
        traceback.print_exc()


# =============================================================================
# Text Processing Pipeline (skip transcription)
# =============================================================================

@app.post('/api/text-block', status_code=202, response_model=ProcessingResponse)
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
    global current_episode_key
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
        async with processing_lock:
            pending_block = {
                "block_id": block_id,
                "timestamp": datetime.now().isoformat(),
                "claims_count": len(claims),
                "claims": [to_dict(c) for c in claims],
                "status": "pending",
                "source_id": source_id,
                "episode_key": current_episode_key or "test",
                "headline": headline,
                "text_preview": text[:200] + "..." if len(text) > 200 else text
            }
            pending_claims_blocks.append(pending_block)

        logger.info(f"[{block_id}] Pipeline complete. {len(claims)} claims added to pending.")

    except Exception as e:
        logger.error(f"[{block_id}] Pipeline error: {e}")
        import traceback
        traceback.print_exc()


# =============================================================================
# Pending Claims Management
# =============================================================================

@app.get('/api/pending-claims')
async def get_pending_claims():
    """Return all pending claim blocks (newest first)"""
    sorted_blocks = sorted(
        pending_claims_blocks,
        key=lambda x: x.get("timestamp", ""),
        reverse=True
    )
    return sorted_blocks


@app.post('/api/pending-claims', status_code=201, response_model=ProcessingResponse)
async def receive_pending_claims(request: PendingClaimsRequest):
    """Receive pending claims (for manual testing or external sources)"""
    global current_episode_key

    block_id = request.block_id or f"block_{int(datetime.now().timestamp() * 1000)}"
    timestamp = request.timestamp or datetime.now().isoformat()
    claims = request.claims
    episode_key = request.episode_key or current_episode_key

    # Ensure unique block_id
    existing_ids = [b.get("block_id") for b in pending_claims_blocks]
    if block_id in existing_ids:
        counter = 1
        base_id = block_id
        while block_id in existing_ids:
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

    async with processing_lock:
        pending_claims_blocks.append(pending_block)

    logger.info(f"Pending claims received: {block_id} with {len(claims)} claims")

    return ProcessingResponse(
        status="success",
        block_id=block_id,
        claims_count=len(claims)
    )


@app.post('/api/approve-claims', status_code=202, response_model=ProcessingResponse)
async def approve_claims(
    request: ClaimApprovalRequest,
    background_tasks: BackgroundTasks
):
    """
    Approve selected claims and start fact-checking.

    Uses local FactChecker service.
    """
    global current_episode_key

    if not request.claims:
        raise HTTPException(status_code=400, detail="No claims selected")

    episode_key = request.episode_key or current_episode_key
    logger.info(f"Approving {len(request.claims)} claims from block {request.block_id}")

    # Try to find context from the pending block
    context = None
    if request.block_id:
        for b in pending_claims_blocks:
            if b.get("block_id") == request.block_id:
                context = b.get("info") or b.get("headline")
                break

    # Start fact-checking in background
    background_tasks.add_task(process_fact_checks_async, request.claims, episode_key, context)

    return ProcessingResponse(
        status="processing",
        message=f"{len(request.claims)} claims submitted for fact-checking",
        claims_count=len(request.claims)
    )


async def process_fact_checks_async(claims: list, episode_key: str, context: str = None):
    """
    Background task: fact-check claims using FactChecker service.
    """
    try:
        logger.info(f"Starting fact-check for {len(claims)} claims...")

        fact_checker = get_fact_checker()

        # Use async method if available, otherwise wrap sync call
        if hasattr(fact_checker, 'check_claims_async'):
            results = await fact_checker.check_claims_async(claims, context=context)
        else:
            results = await asyncio.to_thread(fact_checker.check_claims, claims, context=context)

        # Store results
        async with processing_lock:
            for result in results:
                result_dict = to_dict(result)
                sources = result_dict.get("sources", [])

                fact_check = {
                    "id": len(fact_checks) + 1,
                    "sprecher": result_dict.get("speaker", ""),
                    "behauptung": result_dict.get("original_claim", ""),
                    "consistency": result_dict.get("consistency", "unklar"),
                    "begruendung": result_dict.get("evidence", ""),
                    "quellen": [to_dict(s) for s in sources] if sources else [],
                    "timestamp": datetime.now().isoformat(),
                    "episode_key": episode_key
                }
                fact_checks.append(fact_check)
                logger.info(f"Fact-check complete: {fact_check['sprecher']} - {fact_check['consistency']}")

        # Save to JSON file for GitHub Pages
        if episode_key:
            await asyncio.to_thread(save_fact_checks_to_file, episode_key)

        logger.info(f"Fact-checking complete. {len(results)} results stored.")

    except Exception as e:
        logger.error(f"Error in fact-check processing: {e}")
        import traceback
        traceback.print_exc()


# =============================================================================
# Fact-Check Storage
# =============================================================================

@app.get('/api/fact-checks')
async def get_fact_checks(episode: Optional[str] = Query(default=None)):
    """Return fact-checks, optionally filtered by episode"""
    if episode:
        return [fc for fc in fact_checks if fc.get('episode_key') == episode]
    return fact_checks


@app.post('/api/fact-checks', status_code=201, response_model=FactCheckStoredResponse)
async def receive_fact_check(request: FactCheckRequest):
    """Receive fact-check results (for manual testing or external sources)"""
    global current_episode_key

    # Support both German and English field names
    sprecher = request.sprecher or request.speaker or ""
    behauptung = request.behauptung or request.original_claim or request.claim or ""
    consistency = request.consistency or request.urteil or ""
    begruendung = request.begruendung or request.evidence or ""
    quellen = request.quellen or request.sources or []
    episode_key = request.episode_key or request.episode or current_episode_key

    # Handle string sources
    if isinstance(quellen, str):
        try:
            quellen = json.loads(quellen)
        except:
            quellen = [quellen] if quellen else []

    fact_check = {
        "id": len(fact_checks) + 1,
        "sprecher": sprecher,
        "behauptung": behauptung,
        "consistency": consistency,
        "begruendung": begruendung,
        "quellen": quellen if isinstance(quellen, list) else [],
        "timestamp": datetime.now().isoformat(),
        "episode_key": episode_key
    }

    async with processing_lock:
        fact_checks.append(fact_check)

    logger.info(f"Fact-check stored: ID {fact_check['id']} - {sprecher} - {consistency}")

    if episode_key:
        await asyncio.to_thread(save_fact_checks_to_file, episode_key)

    return FactCheckStoredResponse(status="success", id=fact_check["id"])


@app.put('/api/fact-checks/{fact_check_id}', status_code=202, response_model=ProcessingResponse)
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
    global current_episode_key

    # Find existing fact-check
    existing = None
    for fc in fact_checks:
        if fc.get("id") == fact_check_id:
            existing = fc
            break

    if not existing:
        raise HTTPException(status_code=404, detail=f"Fact-check {fact_check_id} not found")

    episode_key = request.episode_key or existing.get("episode_key") or current_episode_key

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
        async with processing_lock:
            for fc in fact_checks:
                if fc.get("id") == fact_check_id:
                    fc["sprecher"] = result_dict.get("speaker", name)
                    fc["behauptung"] = result_dict.get("original_claim", claim)
                    fc["consistency"] = result_dict.get("consistency", "unklar")
                    fc["begruendung"] = result_dict.get("evidence", "")
                    fc["quellen"] = [to_dict(s) for s in sources] if sources else []
                    fc["timestamp"] = datetime.now().isoformat()
                    fc["episode_key"] = episode_key
                    logger.info(f"Fact-check {fact_check_id} updated: {fc['consistency']}")
                    break

        # Save to JSON file
        if episode_key:
            await asyncio.to_thread(save_fact_checks_to_file, episode_key)

        logger.info(f"Fact-check {fact_check_id} re-run complete.")

    except Exception as e:
        logger.error(f"Error re-running fact-check {fact_check_id}: {e}")
        import traceback
        traceback.print_exc()


def save_fact_checks_to_file(episode_key: str):
    """Save fact-checks for an episode to JSON file for GitHub Pages"""
    try:
        episode_checks = [fc for fc in fact_checks if fc.get('episode_key') == episode_key]

        if not episode_checks:
            logger.warning(f"No fact-checks for episode {episode_key}")
            return

        json_file = DATA_DIR / f"{episode_key}.json"
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(episode_checks, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved {len(episode_checks)} fact-checks to {json_file}")

    except Exception as e:
        logger.error(f"Error saving fact-checks for {episode_key}: {e}")


# =============================================================================
# Configuration Endpoints
# =============================================================================

# NOTE: More specific routes MUST come before the wildcard route
# Otherwise /api/config/shows would match /api/config/{episode_key}

@app.get('/api/config/shows', response_model=ShowsResponse)
async def get_all_shows_endpoint():
    """Return all available shows"""
    try:
        shows = get_all_shows()
        return ShowsResponse(shows=shows)
    except Exception as e:
        logger.error(f"Error loading shows: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/config/shows/{show_key}/episodes', response_model=EpisodesResponse)
async def get_episodes_for_show_endpoint(show_key: str):
    """Return all episodes for a show"""
    try:
        episodes = get_episodes_for_show(show_key)
        return EpisodesResponse(episodes=episodes)
    except Exception as e:
        logger.error(f"Error loading episodes for {show_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get('/api/config/{episode_key}')
async def get_episode_config_endpoint(episode_key: str):
    """Return configuration for an episode"""
    try:
        config = get_show_config(episode_key)
        return config
    except Exception as e:
        logger.error(f"Error loading config for {episode_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/api/set-episode')
async def set_current_episode(request: SetEpisodeRequest):
    """Set the current episode (called by listener)"""
    global current_episode_key

    episode_key = request.episode_key or request.episode
    if episode_key:
        current_episode_key = episode_key
        logger.info(f"Current episode set: {episode_key}")
        return {"status": "success", "episode_key": episode_key}
    else:
        raise HTTPException(status_code=400, detail="episode_key missing")


@app.get('/api/health', response_model=HealthResponse)
async def health():
    """Health check endpoint"""
    return HealthResponse(
        status="ok",
        current_episode=current_episode_key,
        pending_blocks=len(pending_claims_blocks),
        fact_checks=len(fact_checks)
    )


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    import uvicorn
    port = int(os.getenv("PORT", 5000))

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  Fact-Check Backend (FastAPI)                                ║
╠══════════════════════════════════════════════════════════════╣
║  Server:     http://0.0.0.0:{port}                            ║
║  API Docs:   http://0.0.0.0:{port}/docs                       ║
║                                                              ║
║  Endpoints:                                                  ║
║    POST /api/audio-block     - Receive audio from listener   ║
║    POST /api/text-block      - Receive text from reader      ║
║    GET  /api/pending-claims  - Get pending claims            ║
║    POST /api/approve-claims  - Approve claims for checking   ║
║    GET  /api/fact-checks     - Get completed fact-checks     ║
║    PUT  /api/fact-checks/id  - Re-run fact-check (overwrite) ║
║    GET  /api/health          - Health check                  ║
╚══════════════════════════════════════════════════════════════╝
    """)

    uvicorn.run("backend.app:app", host="0.0.0.0", port=port, reload=True)
