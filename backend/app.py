"""
Fact-Check Backend API

Flask server that handles:
- Audio block processing (transcription + claim extraction)
- Pending claims management
- Fact-check processing and storage
- Episode configuration
"""

import os
import sys
import json
import logging
import tempfile
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

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
    from config import get_show_config, get_all_shows, get_episodes_for_show, get_guests
except ImportError:
    logger.warning("config.py not found. Using default configuration.")
    def get_show_config(episode_key=None):
        return {"speakers": [], "guests": "", "name": "Unknown", "description": ""}
    def get_all_shows():
        return []
    def get_episodes_for_show(show_key):
        return []
    def get_guests(episode_key=None):
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


# Flask app
app = Flask(__name__)

# CORS configuration
CORS(app, resources={
    r"/api/*": {
        "origins": [
            "https://mertensu.github.io",
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173"
        ],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "Accept"]
    }
})

# In-memory storage
fact_checks = []
pending_claims_blocks = []
current_episode_key = None
processing_lock = threading.Lock()

# Background executor for async processing
executor = ThreadPoolExecutor(max_workers=5)

# Path for JSON files (for GitHub Pages)
DATA_DIR = Path(__file__).parent.parent / "frontend" / "public" / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Audio Processing Pipeline
# =============================================================================

@app.route('/api/audio-block', methods=['POST'])
def receive_audio_block():
    """
    Receive audio block from listener.py and start processing pipeline.

    Expected: multipart form data with:
    - audio: WAV file
    - episode_key: Episode identifier
    - guests: (optional) Guest information override
    """
    try:
        # Check for audio file
        if 'audio' not in request.files:
            return jsonify({"status": "error", "message": "No audio file provided"}), 400

        audio_file = request.files['audio']
        episode_key = request.form.get('episode_key', current_episode_key or 'test')
        guests = request.form.get('guests') or get_guests(episode_key)

        # Read audio data
        audio_data = audio_file.read()

        logger.info(f"Received audio block: {len(audio_data)} bytes, episode: {episode_key}")

        # Start background processing
        executor.submit(process_audio_pipeline, audio_data, episode_key, guests)

        return jsonify({
            "status": "processing",
            "message": "Audio received, processing started",
            "episode_key": episode_key
        }), 202

    except Exception as e:
        logger.error(f"Error receiving audio block: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400


def process_audio_pipeline(audio_data: bytes, episode_key: str, guests: str):
    """
    Background pipeline: audio -> transcription -> claim extraction -> pending claims
    """
    block_id = f"block_{int(datetime.now().timestamp() * 1000)}"

    try:
        logger.info(f"[{block_id}] Starting audio processing pipeline...")

        # Step 1: Transcription
        logger.info(f"[{block_id}] Step 1: Transcribing audio...")
        transcription_service = get_transcription_service()
        transcript = transcription_service.transcribe(audio_data)
        logger.info(f"[{block_id}] Transcription complete: {len(transcript)} chars")

        # Step 2: Claim extraction
        logger.info(f"[{block_id}] Step 2: Extracting claims...")
        claim_extractor = get_claim_extractor()
        claims = claim_extractor.extract(transcript, guests)
        logger.info(f"[{block_id}] Extracted {len(claims)} claims")

        if not claims:
            logger.info(f"[{block_id}] No claims extracted, skipping")
            return

        # Step 3: Store as pending claims
        with processing_lock:
            pending_block = {
                "block_id": block_id,
                "timestamp": datetime.now().isoformat(),
                "claims_count": len(claims),
                "claims": claims,
                "status": "pending",
                "episode_key": episode_key,
                "transcript_preview": transcript[:200] + "..." if len(transcript) > 200 else transcript
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

@app.route('/api/pending-claims', methods=['GET'])
def get_pending_claims():
    """Return all pending claim blocks (newest first)"""
    sorted_blocks = sorted(
        pending_claims_blocks,
        key=lambda x: x.get("timestamp", ""),
        reverse=True
    )
    return jsonify(sorted_blocks)


@app.route('/api/pending-claims', methods=['POST'])
def receive_pending_claims():
    """Receive pending claims (for manual testing or external sources)"""
    try:
        data = request.get_json()

        block_id = data.get("block_id") or f"block_{int(datetime.now().timestamp() * 1000)}"
        timestamp = data.get("timestamp") or datetime.now().isoformat()
        claims = data.get("claims", [])
        episode_key = data.get("episode_key", current_episode_key)

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

        with processing_lock:
            pending_claims_blocks.append(pending_block)

        logger.info(f"Pending claims received: {block_id} with {len(claims)} claims")

        return jsonify({
            "status": "success",
            "block_id": block_id,
            "claims_count": len(claims)
        }), 201

    except Exception as e:
        logger.error(f"Error receiving pending claims: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route('/api/approve-claims', methods=['POST'])
def approve_claims():
    """
    Approve selected claims and start fact-checking.

    No longer sends to N8N - uses local FactChecker service.
    """
    try:
        data = request.get_json()
        selected_claims = data.get("claims", [])
        block_id = data.get("block_id")
        episode_key = data.get("episode_key", current_episode_key)

        if not selected_claims:
            return jsonify({"status": "error", "message": "No claims selected"}), 400

        logger.info(f"Approving {len(selected_claims)} claims from block {block_id}")

        # Start fact-checking in background
        executor.submit(process_fact_checks, selected_claims, episode_key)

        return jsonify({
            "status": "processing",
            "message": f"{len(selected_claims)} claims submitted for fact-checking",
            "claims_count": len(selected_claims)
        }), 202

    except Exception as e:
        logger.error(f"Error approving claims: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400


def process_fact_checks(claims: list, episode_key: str):
    """
    Background task: fact-check claims using FactChecker service.
    """
    try:
        logger.info(f"Starting fact-check for {len(claims)} claims...")

        fact_checker = get_fact_checker()
        results = fact_checker.check_claims(claims)

        # Store results
        with processing_lock:
            for result in results:
                fact_check = {
                    "id": len(fact_checks) + 1,
                    "sprecher": result.get("speaker", ""),
                    "behauptung": result.get("original_claim", ""),
                    "urteil": result.get("verdict", "Unbelegt"),
                    "begruendung": result.get("evidence", ""),
                    "quellen": result.get("sources", []),
                    "timestamp": datetime.now().isoformat(),
                    "episode_key": episode_key
                }
                fact_checks.append(fact_check)

                logger.info(f"Fact-check complete: {fact_check['sprecher']} - {fact_check['urteil']}")

        # Save to JSON file for GitHub Pages
        if episode_key:
            save_fact_checks_to_file(episode_key)

        logger.info(f"Fact-checking complete. {len(results)} results stored.")

    except Exception as e:
        logger.error(f"Error in fact-check processing: {e}")
        import traceback
        traceback.print_exc()


# =============================================================================
# Fact-Check Storage
# =============================================================================

@app.route('/api/fact-checks', methods=['GET'])
def get_fact_checks():
    """Return fact-checks, optionally filtered by episode"""
    episode_key = request.args.get('episode')
    if episode_key:
        filtered = [fc for fc in fact_checks if fc.get('episode_key') == episode_key]
        return jsonify(filtered)
    return jsonify(fact_checks)


@app.route('/api/fact-checks', methods=['POST'])
def receive_fact_check():
    """Receive fact-check results (for manual testing or external sources)"""
    try:
        data = request.get_json()

        # Support both German and English field names
        sprecher = data.get("sprecher") or data.get("speaker") or ""
        behauptung = data.get("behauptung") or data.get("original_claim") or data.get("claim") or ""
        urteil = data.get("urteil") or data.get("verdict") or ""
        begruendung = data.get("begruendung") or data.get("evidence") or ""
        quellen = data.get("quellen") or data.get("sources") or []
        episode_key = data.get("episode_key") or data.get("episode") or current_episode_key

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
            "urteil": urteil,
            "begruendung": begruendung,
            "quellen": quellen if isinstance(quellen, list) else [],
            "timestamp": datetime.now().isoformat(),
            "episode_key": episode_key
        }

        with processing_lock:
            fact_checks.append(fact_check)

        logger.info(f"Fact-check stored: ID {fact_check['id']} - {sprecher} - {urteil}")

        if episode_key:
            save_fact_checks_to_file(episode_key)

        return jsonify({"status": "success", "id": fact_check["id"]}), 201

    except Exception as e:
        logger.error(f"Error receiving fact-check: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400


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

@app.route('/api/config/<episode_key>', methods=['GET'])
def get_episode_config_endpoint(episode_key):
    """Return configuration for an episode"""
    try:
        config = get_show_config(episode_key)
        return jsonify(config)
    except Exception as e:
        logger.error(f"Error loading config for {episode_key}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/config/shows', methods=['GET'])
def get_all_shows_endpoint():
    """Return all available shows"""
    try:
        shows = get_all_shows()
        return jsonify({"shows": shows})
    except Exception as e:
        logger.error(f"Error loading shows: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/config/shows/<show_key>/episodes', methods=['GET'])
def get_episodes_for_show_endpoint(show_key):
    """Return all episodes for a show"""
    try:
        episodes = get_episodes_for_show(show_key)
        return jsonify({"episodes": episodes})
    except Exception as e:
        logger.error(f"Error loading episodes for {show_key}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/set-episode', methods=['POST'])
def set_current_episode():
    """Set the current episode (called by listener)"""
    global current_episode_key
    try:
        data = request.get_json()
        episode_key = data.get("episode_key") or data.get("episode")
        if episode_key:
            current_episode_key = episode_key
            logger.info(f"Current episode set: {episode_key}")
            return jsonify({"status": "success", "episode_key": episode_key})
        else:
            return jsonify({"status": "error", "message": "episode_key missing"}), 400
    except Exception as e:
        logger.error(f"Error setting episode: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "ok",
        "current_episode": current_episode_key,
        "pending_blocks": len(pending_claims_blocks),
        "fact_checks": len(fact_checks)
    })


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    port = int(os.getenv("FLASK_PORT", 5000))

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║  Fact-Check Backend                                          ║
╠══════════════════════════════════════════════════════════════╣
║  Server:     http://0.0.0.0:{port}                            ║
║                                                              ║
║  Endpoints:                                                  ║
║    POST /api/audio-block     - Receive audio from listener   ║
║    GET  /api/pending-claims  - Get pending claims            ║
║    POST /api/approve-claims  - Approve claims for checking   ║
║    GET  /api/fact-checks     - Get completed fact-checks     ║
║    GET  /api/health          - Health check                  ║
╚══════════════════════════════════════════════════════════════╝
    """)

    app.run(debug=True, host='0.0.0.0', port=port)
