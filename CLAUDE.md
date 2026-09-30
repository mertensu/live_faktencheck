# CLAUDE.md

This file provides guidance to AI coding assistants (Claude Code, Cursor, Copilot, etc.) when working with this repository.

## Project Overview

**Live Faktencheck** is a real-time fact-checking system for German TV talk shows. It streams live audio into a transcript, gates each few sentences for checkable claims, and fact-checks them automatically — results appear as marks in the live transcript.

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

# 2. Run tests (fast, no API calls — every model is mocked)
uv run pytest backend/tests                              # Backend unit tests
uv run pytest backend/tests -k "test_name"               # Single test
uv run pytest backend/tests/test_models.py               # Specific file
cd frontend && bun run test                              # Frontend unit tests (vitest)

# 3. Lint before committing
uv run ruff check backend/                               # Check for issues
uv run ruff check --fix backend/                         # Auto-fix issues

# 4. Build frontend before committing frontend changes
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

# Build
cd frontend && bun run build         # Build frontend for deployment
```

### Production (VPS)
The backend runs as a container on the project's VPS; the frontend reads the live API. See `docs/deployment.md`. **Deploying is merging a PR into `main`** — CI builds the image, the server pulls it within a few minutes. Do not deploy by hand.

**To look at real data, do not reach for SSH.** `./scripts/pull-db.sh` restores a snapshot
from R2 into `backend/data/factcheck.db` using the read-only R2 token from `.env` — no server
access needed, and it works for everyone on the team:
```bash
./scripts/pull-db.sh                      # latest snapshot
./scripts/pull-db.sh 2026-09-08T21:00:00Z # a point in time
sqlite3 backend/data/factcheck.db 'SELECT ...'
```

Shell access to the server is held by maintainers only, and is reserved for operating the
machine itself — not for deploys, not for reading data, not for editing claims. Assume you
do not have it: if a task seems to need it, there is almost always a path through the API,
`pull-db.sh`, or Logfire. Key paths there, for context:
- App directory: `/opt/fact_check/` (compose files and scripts; the app ships as an image)
- Live database: `/opt/fact_check/backend/data/factcheck.db` (SQLite, bind-mounted)
- Container: `factcheck-backend`, deploy timer `factcheck-deploy.timer`

Never write to the live DB from a session, and never copy the live file while it is being
written — `pull-db.sh` exists precisely to avoid both.

## Architecture Overview

### Data Flow
```
Browser mic -> Streaming transcription -> Claim gate -> Fast check -> Live transcript
  (WebSocket)   (AssemblyAI streaming)   (Gemini window  (parallel Tavily  (marks + result
                                          gate or Jev +   + one Gemini      on click)
                                          reformulation)  synthesis call)
```

See `docs/llm_pipeline.md` for the LLM calls. The old block pipeline, deep ReAct checker and
Quick Check were removed in v0.3.0 (code still in tag `v0.2.0`); stored deep-check rows
(`check_depth="deep"`) are display-only.

### Backend Structure (`backend/`)

```
backend/
  app.py              # FastAPI app entry point, includes routers
  state.py            # Shared in-memory state (DB handle, open live streams)
  models.py           # Pydantic request/response models
  auth.py             # Access-code gate (X-Access-Code), ACCESS_CODES seeding
  database.py         # SQLite (fact_checks, sessions, codes)
  routers/
    stream.py         # WS /api/stream — live audio in, transcript/claim events out
    sessions.py       # /api/sessions create/get/end
    fact_checks.py    # /api/fact-checks GET/POST/DELETE
    config.py         # /api/config/*, /api/health, /api/validate-code, /api/trusted-domains
  services/
    streaming.py      # StreamingSession: AssemblyAI streaming, windowing, orchestration
    gate.py           # Claim gate: ExtractorGate (default) or JevGate
    claim_extraction.py # Window-gate and reformulation agents (PydanticAI + Gemini)
    fast_fact_checker.py # Parallel Tavily searches + one synthesis call
    search.py         # Tavily wrapper restricted to trusted domains
    llm_base.py       # Model chain with Gemini + cross-provider fallback
    transcription.py  # AssemblyAI region host + keyterms helpers
    trusted_domains.py # Trusted domains dict (categories, source tiers)
  lang.py             # German strings for LLM field descriptions (change here to adapt language)
  utils.py            # load_prompt() and shared utility functions
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
    useAudioStream.js # Live stream: mic -> PCM worklet -> WebSocket, transcript/claim state
    useMicDevices.js  # Mic picker state
  components/
    Navigation.jsx    # Top navigation bar
    Footer.jsx        # Footer component
    LiveTranscript.jsx # Live transcript with claim marks and speaker assignment
    LiveTutorial.jsx  # Kurzanleitung for operators
    FactCheckStream.jsx # Results stream (viewers, Beispiele)
    ClaimCard.jsx     # Verdict colors/formatting helpers
    MicSelect.jsx     # Mic picker
    ShareLink.jsx     # View-only link for viewers
    BackendErrorDisplay.jsx # Error display
  pages/
    HomePage.jsx      # Home page
    AboutPage.jsx     # About page
    NewSessionPage.jsx # /new — session wizard
    ExamplesPage.jsx  # /beispiele — past sessions
    FactCheckPage.jsx # /:episodeKey — live session / results
    TrustedDomainsPage.jsx # /trusted-domains - auto-updating domain list
```

### Key Patterns

- **Backend**: FastAPI routers with shared state module, lazy-loaded AI services
- **Frontend**: React hooks for data fetching, component-based architecture
- **API**: one WebSocket per live session drives the whole pipeline; results are polled via `/api/fact-checks`
- **Config**: Episode/show configuration in `config.py` (typed `Episode` dataclass + `EPISODES` dict), prompts in `prompts/`, LLM field descriptions in `backend/lang.py`

## Environment Variables

Required API keys in `.env`:
- `ASSEMBLYAI_API_KEY` - Transcription
- `GEMINI_API_KEY` or `GOOGLE_API_KEY` - LLM
- `TAVILY_API_KEY` - Web search
- `ACCESS_CODES` - Access-code seeds (`name:code[:unlimited]`); the gate is fail-closed

Optional (full list in `docs/configuration.md`):
- `CLAIM_GATE` - `extractor` (default) or `jev`
- `GEMINI_MODEL_WINDOW_GATE`, `GEMINI_MODEL_REFORMULATE`, `GEMINI_MODEL_FAST_CHECK` - live-lane models
- `REQUESTY_API_KEY` - enables the Jev gate and the cross-provider fallback
- `VITE_BACKEND_URL` - Frontend backend URL for production
