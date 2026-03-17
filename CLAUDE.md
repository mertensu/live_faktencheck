# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Session Memory System

**CRITICAL - At session start (before doing ANYTHING else):** Read `memory.md` AND the most recent file in `handover/` (by date). Do this as the very first action, even before reading files the user mentions or answering questions. This is mandatory - the user must not have to re-explain context from previous sessions.

**At session end (when the user says goodbye, ends the session, says "handover", or asks for a handover):**
1. **Update `memory.md`** - Add/update any new decisions, issues, things that worked/failed, and recent changes. Keep it concise and cumulative. Remove outdated info.
2. **Create `handover/YYYY-MM-DD_brief-topic.md`** - Write a session-specific handover with:
   - What was accomplished this session
   - What's in progress / next steps
   - Any open questions or blockers
   - Key files that were modified

This ensures the next session has full context without re-explanation.

**Proactive handover reminders:** When the conversation is getting long (roughly 30+ back-and-forth exchanges, or after significant context compression has occurred), proactively suggest: "This session is getting long - want me to write a handover now so nothing is lost?" Keep working if the user declines, but remind again after another ~15 exchanges. When context compression happens (you notice gaps in your memory of earlier conversation), **immediately** offer to write the handover.

## Python Environment

Use `uv run python` to run Python scripts, or activate the venv first:
```bash
uv run python script.py
# or
source .venv/bin/activate && python script.py
```

## Development Workflow

**Always use `bun`, not `npm`.** Always use `uv`, not `pip`.

```sh
# 1. Make changes

# 2. Run tests (fast, no API calls)
uv run pytest backend/tests -m "not integration"         # Unit tests only
uv run pytest backend/tests -k "test_name"               # Single test
uv run pytest backend/tests/test_models.py               # Specific file

# 3. Run integration tests (requires API keys)
uv run pytest backend/tests -m integration               # API-dependent tests
FACT_CHECK_RECURSION_LIMIT=5 uv run pytest               # Lower limit for faster runs

# 4. Lint before committing
uv run ruff check backend/                               # Check for issues
uv run ruff check --fix backend/                         # Auto-fix issues

# 5. Build frontend before committing frontend changes
cd frontend && bun run build
```

## Git Commits

- Use short, concise commit messages (one line)
- Do not add co-author information to commit messages

## Common Commands

```bash
# Install dependencies
uv sync                              # Python dependencies
cd frontend && bun install           # Frontend dependencies

# Development
./start_dev.sh <episode-key>         # Start backend + frontend together (preferred)
./backend/run.sh                     # Start backend only (port 5000)
cd frontend && bun run dev           # Start frontend dev server only (port 3000)

# Production
./start_production.sh <episode-key>  # Start tunnel, backend, frontend
uv run python listener.py <episode>  # Start audio listener (separate terminal)
./stop_production.sh                 # Stop all services

# Build
cd frontend && bun run build         # Build frontend for deployment

# Delete a claim (e.g. wrong/unwanted fact-check)
# 1. Delete from DB by ID
uv run python -c "import sqlite3; conn = sqlite3.connect('backend/data/factcheck.db'); conn.execute('DELETE FROM fact_checks WHERE id = <ID>'); conn.commit(); conn.close()"
# 2. Re-export JSON from DB (overwrites the static file cleanly)
uv run python export_episode.py --json <episode-key>
# 3. Commit + push

# Re-run (overwrite) existing claims for a published episode
# 1. Start backend: ./start_dev.sh <episode-key>
# 2. Open admin mode in browser → "Gesendete Claims" is pre-populated from DB
# 3. Click "Re-send" on the claim(s) → they appear in Pending Claims
# 4. Approve from staging → fact-checker overwrites the existing DB record (not a new entry)
# 5. Re-export: uv run python export_episode.py --json <episode-key>
# 6. Commit + push

# Index local PDFs for RAG (run before show if episode has reference_pdfs)
# Store PDFs in a local pdfs/ dir (gitignored). Configure in config.py:
#   reference_pdfs=["pdfs/wahlprogramm-afd-2025.pdf"]
uv run python index_pdfs.py <episode-key>
uv run python index_pdfs.py <episode-key> --force   # rebuild existing index
```

## Architecture Overview

**Live Faktencheck** is a real-time fact-checking system for German TV talk shows.

### Data Flow
```
Audio -> Transcription -> Claim Extraction -> Admin Review -> Fact-Checking -> Display
         (AssemblyAI)    (Gemini)           (React UI)      (LangChain+Tavily)
```

### Backend Structure (`backend/`)

```
backend/
  app.py              # FastAPI app entry point, includes routers
  state.py            # Shared in-memory state (fact_checks, pending_claims)
  models.py           # Pydantic request/response models
  routers/
    audio.py          # /api/audio-block endpoint
    claims.py         # /api/pending-claims, /api/text-block, /api/approve-claims
    fact_checks.py    # /api/fact-checks CRUD, /api/fact-checks/resend
    config.py         # /api/config/*, /api/health, /api/set-episode
  routers/
    pipeline.py       # /api/pipeline/* pipeline status GET/POST endpoints
  services/
    transcription.py  # AssemblyAI integration
    claim_extraction.py # Gemini-based claim extraction
    fact_checker.py   # LangChain ReAct agent with Tavily search
    trusted_domains.py # Trusted domains dict (categories)
  utils.py            # load_lang_config() for lang_de.toml (lru_cache)
```

### Frontend Structure (`frontend/src/`)

```
frontend/src/
  App.jsx             # Main app with routing
  App.css             # Styles
  services/
    api.js            # Backend URL, fetch helpers, debug logging
  hooks/
    useShows.js       # Custom hook for loading shows
  components/
    Navigation.jsx    # Top navigation bar
    Footer.jsx        # Footer component
    ClaimCard.jsx     # Fact-check display card with markdown
    AdminView.jsx     # Admin panel for claim management
    SpeakerColumns.jsx # Speaker columns layout
    BackendErrorDisplay.jsx # Error display
  components/
    ClaimDetailOverlay.jsx # Claim detail modal overlay
  pages/
    HomePage.jsx      # Home page with show list
    AboutPage.jsx     # About page
    ShowPage.jsx      # Show page with episode selector
    FactCheckPage.jsx # Main fact-check dashboard
    TrustedDomainsPage.jsx # /trusted-domains - auto-updating domain list
```

### Key Patterns

- **Backend**: FastAPI routers with shared state module, lazy-loaded AI services
- **Frontend**: React hooks for data fetching, component-based architecture
- **API**: Async background tasks for processing pipelines
- **Config**: Episode/show configuration in `config.py` (typed `Episode` dataclass + `EPISODES` dict), prompts in `prompts/`, LLM field descriptions in `prompts/lang_de.toml`

## Environment Variables

Required API keys in `.env`:
- `ASSEMBLYAI_API_KEY` - Transcription
- `GEMINI_API_KEY` or `GOOGLE_API_KEY` - LLM
- `TAVILY_API_KEY` - Web search

Optional:
- `GEMINI_MODEL_CLAIM_EXTRACTION` (default: gemini-2.5-flash)
- `GEMINI_MODEL_FACT_CHECKER` (default: gemini-2.5-pro)
- `FACT_CHECK_RECURSION_LIMIT` - Max agent iterations (default: 25, use 5-10 for tests)
- `VITE_BACKEND_URL` - Frontend backend URL for production
- `VITE_N8N_WEBHOOK_URL` - N8N webhook (optional)
- `LANG` - Language for `lang_de.toml` lookup (set to `de` in `.env`)
