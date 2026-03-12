# Live Faktencheck

Real-time fact-checking system for German TV talk shows. Captures audio, extracts claims, and verifies them against authoritative sources.

## How It Works

```
  Live Audio Stream
  ┌──────────┬──────────┬──────────┬──────────┐
  │  Block 1 │  Block 2 │  Block 3 │  Block 4 │  ──▶
  └──────────┴──────────┴──────────┴──────────┘
                    │ per block
                    ▼
┌──────────────┐  ┌─────────────────┐  ┌──────────────────┐  ┌──────────────────────┐  ┌──────────────────┐
│Transcription │─▶│Claim Extraction │─▶│Human-in-the-Loop │─▶│    Fact-Checking     │─▶│    Display       │
│ (AssemblyAI) │  │    (LLM)        │  │ approve / discard│  │  ┌────────────────┐  │  │ verdict +        │
└──────────────┘  └─────────────────┘  └──────────────────┘  │  │Reason → Search │  │  │ explanation +    │
                                                              │  │  → Evaluate    │  │  │ sources          │
                                                              │  └──────↺─────────┘  │  └──────────────────┘
                                                              │  (LLM + Web Search)  │
                                                              └──────────────────────┘
```

1. **Audio Capture**: Listener captures audio via BlackHole virtual audio device
2. **Transcription**: AssemblyAI transcribes with speaker detection
3. **Claim Extraction**: Gemini extracts verifiable factual claims
4. **Human Review**: Admin UI allows editing and approval of claims
5. **Fact-Checking**: LangChain agent with Gemini + Tavily verifies claims against trusted German sources
6. **Display**: Results shown on Cloudflare Pages (public) and local admin UI

## Requirements

- Python 3.11+
- Node.js 20+
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/) (Cloudflare Tunnel)
- [BlackHole](https://existential.audio/blackhole/) (virtual audio device for macOS)

## API Keys Required

Create a `.env` file (see `.env.example`):

```bash
ASSEMBLYAI_API_KEY=your_key    # Transcription
GEMINI_API_KEY=your_key        # Claim extraction & fact-checking
TAVILY_API_KEY=your_key        # Web search for fact-checking
LANG=de                        # Language for LLM prompts
```

## Installation

```bash
# Clone the repo
git clone https://github.com/mertensu/live_faktencheck.git
cd live_faktencheck

# Install Python dependencies
uv sync

# Install frontend dependencies
cd frontend && bun install && cd ..

# Copy env template and add your API keys
cp .env.example .env
```

## Workflows

### Live Fact-Check (on air)

Run a live session where results appear in real-time on the public domain.

**Before the show** — add the episode to `config.py` with `publish=True` and push to GitHub (Cloudflare deploys automatically):

```python
# In config.py — add a new Episode to the EPISODES dict
EPISODES = {
    "maischberger-2026-03-01": Episode(
        key="maischberger-2026-03-01",
        show="maischberger",
        date="1. März 2026",
        guests=[
            "Sandra Maischberger (Moderatorin)",
            "Guest A (Partei)",
            "Guest B (Partei)",
        ],
        publish=True,   # appears on live-faktencheck.de
    ),
    # ... existing episodes
}
```

```bash
git add config.py && git commit -m "add maischberger-2026-03-01" && git push
```

**During the show** — start backend + Cloudflare Tunnel, then the audio listener:

```bash
# Terminal 1: start backend, tunnel, local admin UI
./start_production.sh maischberger-2026-03-01

# Terminal 2: start audio capture
uv run python listener.py maischberger-2026-03-01
```

- Route your audio through BlackHole into the listener
- Review extracted claims at **http://localhost:3000** (Admin UI, local only)
- Approve claims → fact-checking runs automatically
- Results appear live at **https://live-faktencheck.de/maischberger-2026-03-01**

**After the show** — export results as static files so the page stays online without a running backend:

```bash
./stop_production.sh --permanent
```

This exports the SQLite data to `frontend/public/data/<episode>.json`, commits, pushes, and waits for Cloudflare to build before shutting down the tunnel. No downtime.

---

### Development / Testing

Test the full pipeline locally — same tools as production, but without the Cloudflare tunnel. Nothing goes live.

```bash
# Terminal 1: start backend + admin UI (no tunnel)
./start_dev.sh atalay-2026-02-09   # inherits Atalay's speakers and config

# Terminal 2: start audio capture
uv run python listener.py atalay-2026-02-09
```

- Review extracted claims at **http://localhost:3000** (Admin UI)
- Approve claims → fact-checking runs automatically
- Results visible locally only — nothing appears on the public domain

To simulate a claim without audio, POST directly to the backend:

```bash
curl -X POST http://localhost:5000/api/text-block \
  -H "Content-Type: application/json" \
  -d '{"text": "Deutschland hat 84 Millionen Einwohner.", "episode_key": "atalay-2026-02-09"}'
```

Stop with `./stop_production.sh` (same stop script works for both modes).

---

### Export an Archived Episode

Re-export or update an already-finished episode (e.g. after correcting a claim):

```bash
# Export as static JSON for deployment
uv run python export_episode.py <episode-key> --json

# Export as Markdown (e.g. for publication)
uv run python export_episode.py <episode-key> --order "Sprecher1,Sprecher2"
```

After `--json`, commit and push `frontend/public/data/<episode>.json` to redeploy.

## Database & Static JSON Deployment

### SQLite Database

All fact-checks are stored in `backend/data/factcheck.db` (SQLite). This is the single source of truth during a live session. The database is **not** committed to git.

### Static JSON for Cloudflare Pages

Since there is no always-on backend server, finished episodes are served as static JSON files from `frontend/public/data/`. These files **are** committed to git and deployed via Cloudflare Pages.

```
frontend/public/data/
├── shows.json              # Index of all episodes (auto-updated)
├── atalay-2026-02-09.json  # Per-episode fact-checks
├── lanz-2026-02-06.json
└── ...
```

**When to export**: Run `export_episode.py --json` after any live session, or any time you edit a fact-check in the DB and want the change reflected on the public site.

```bash
uv run python export_episode.py <episode-key> --json
# → writes frontend/public/data/<episode-key>.json
# → rewrites frontend/public/data/shows.json (full episode index)
```

The `shows.json` index is always rewritten from `EPISODES` in `config.py`. It contains **all** episodes — the frontend filters by `publish: true` on the production domain.

### The `publish` Flag

The `publish` flag in `config.py` controls which episodes are visible on the public domain (`live-faktencheck.de`). Episodes without `publish=True` only show up in local development:

```python
Episode(
    key="maischberger-2026-03-01",
    publish=True,   # visible on live-faktencheck.de
    # publish=False  (default) → dev only
)
```

The static JSON for unpublished episodes can still exist in `frontend/public/data/` — the frontend simply won't list or link to them on the production domain.

## Project Structure

```
├── backend/
│   ├── app.py                 # FastAPI server
│   ├── data/
│   │   └── factcheck.db       # SQLite database (not in git)
│   └── services/
│       ├── transcription.py   # AssemblyAI integration
│       ├── claim_extraction.py # Gemini claim extraction
│       ├── fact_checker.py    # LangChain agent with Gemini + Tavily
│       └── trusted_domains.py # Trusted source domains (categorized)
├── frontend/
│   ├── src/App.jsx            # React frontend
│   └── public/data/           # Static JSON exports (served by Cloudflare)
│       ├── shows.json         # Episode index
│       └── <episode-key>.json # Per-episode fact-checks
├── prompts/
│   ├── claim_extraction.md    # Prompt for extracting claims
│   ├── fact_checker.md        # Prompt for fact-checking
│   └── lang_de.toml           # LLM field descriptions (German)
├── listener.py                # Audio capture with fixed-interval sending
├── export_episode.py          # Export episode from DB as JSON or Markdown
├── config.py                  # Episode configuration (EPISODES dict)
├── start_dev.sh               # Development startup (backend + frontend, no tunnel)
├── start_production.sh        # Production startup script
└── stop_production.sh         # Stop all services (--permanent to export & deploy)
```

## Configuration

Episodes are configured in `config.py` using the `Episode` dataclass. The `publish` flag controls visibility on the public domain:

```python
from config import Episode, EPISODES

EPISODES = {
    "maischberger-2025-09-19": Episode(
        key="maischberger-2025-09-19",
        show="maischberger",
        date="19. September 2025",
        guests=[
            "Sandra Maischberger (Moderatorin)",
            "Gitta Connemann (CDU)",
            "Katharina Dröge (B90/Grüne)",
        ],
        publish=True,   # show on live-faktencheck.de
    )
}
```

Available fields:
- `show` — key into `SHOWS` dict (e.g. `"maischberger"`, `"lanz"`)
- `date` — broadcast date string (e.g. `"19. September 2025"`)
- `guests` — list of `"Name (Role/Partei)"` strings; moderator first
- `context` — optional background context passed to the LLM
- `reference_links` — optional list of reference URLs (legislation, press releases)
- `publish` — `True` = visible on production domain (default: `False`)
- `type` — `"show"` or `"youtube"` (default: `"show"`)

## Trusted Sources

Fact-checking searches are restricted to authoritative German sources, organized by category (government, research, media, EU, etc.). See `backend/services/trusted_domains.py` for the full categorized list, or visit `/trusted-domains` on the running frontend.

## How Fact-Checking Works

The fact-checker uses a LangChain ReAct agent that iteratively searches for evidence:

```
┌─────────────────────────────────────────────────────────┐
│                  LangChain Agent Loop                   │
├─────────────────────────────────────────────────────────┤
│  1. LLM receives claim + conversation history           │
│  2. LLM decides: search for more evidence OR respond    │
│  3. If search: Execute Tavily → append results → repeat │
│  4. If respond: Return consistency rating + evidence + sources │
└─────────────────────────────────────────────────────────┘
```

- **Tavily Search**: Searches the web, filtered to trusted domains only
- **Recursion limit**: Default 25 super-steps to prevent infinite loops (configurable via `FACT_CHECK_RECURSION_LIMIT`)
- **Robust handling**: LangChain guarantees a final response (no silent failures)

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ASSEMBLYAI_API_KEY` | AssemblyAI API key for transcription | Yes |
| `GEMINI_API_KEY` | Google Gemini API key | Yes |
| `TAVILY_API_KEY` | Tavily API key for web search | Yes |
| `LANG` | Language for LLM prompts (set to `de`) | Yes |
| `GEMINI_MODEL_CLAIM_EXTRACTION` | Model for claim extraction (default: gemini-2.5-flash) | No |
| `GEMINI_MODEL_FACT_CHECKER` | Model for fact-checking (default: gemini-2.5-pro) | No |
| `FACT_CHECK_RECURSION_LIMIT` | Max agent iterations (default: 25, use lower for tests) | No |
| `VITE_BACKEND_URL` | Backend URL for production frontend | No |

## License

MIT
