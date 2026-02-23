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

**Before the show** — add the episode to `config.py` with `publish: True` and push to GitHub (Cloudflare deploys automatically):

```python
SHOW_CONFIG = {
    "maischberger-2026-03-01": {
        "name": "Maischberger",
        "speakers": ["Sandra Maischberger", "Guest A", "Guest B"],
        "info": "Episode description...",
        "show": "maischberger",
        "episode_name": "1. März 2026",
        "publish": True        # appears on live-faktencheck.de
    }
}
```

```bash
git add config.py && git commit -m "Add maischberger-2026-03-01" && git push
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

### Development / Debugging

Test the pipeline locally without Cloudflare or audio capture.

```bash
# Terminal 1: backend
./backend/run.sh

# Terminal 2: frontend dev server (includes Admin UI)
cd frontend && bun run dev
```

Open **http://localhost:3000** — Admin UI is always enabled on localhost.

To simulate a claim without audio, POST directly to the backend:

```bash
curl -X POST http://localhost:5000/api/text-block \
  -H "Content-Type: application/json" \
  -d '{"text": "Deutschland hat 84 Millionen Einwohner.", "episode_key": "test"}'
```

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

## Project Structure

```
├── backend/
│   ├── app.py                 # FastAPI server
│   └── services/
│       ├── transcription.py   # AssemblyAI integration
│       ├── claim_extraction.py # Gemini claim extraction
│       └── fact_checker.py    # LangChain agent with Gemini + Tavily
├── frontend/
│   ├── src/App.jsx            # React frontend
│   └── public/data/           # Static JSON exports (served by Cloudflare)
├── prompts/
│   ├── claim_extraction.md    # Prompt for extracting claims
│   └── fact_checker.md        # Prompt for fact-checking
├── listener.py                # Audio capture with fixed-interval sending
├── export_episode.py          # Export episode from DB as JSON or Markdown
├── config.py                  # Episode configuration
├── start_production.sh        # Production startup script
└── stop_production.sh         # Stop all services (--permanent to export & deploy)
```

## Configuration

Episodes are configured in `config.py`. The `publish` flag controls visibility on the public domain (episodes without it only appear in development):

```python
SHOW_CONFIG = {
    "maischberger-2025-09-19": {
        "name": "Maischberger",
        "speakers": ["Sandra Maischberger", "Gitta Connemann", "Katharina Dröge"],
        "info": "Description of the episode...",
        "show": "maischberger",
        "episode_name": "19. September 2025",
        "publish": True        # show on live-faktencheck.de
    }
}
```

## Trusted Sources

Fact-checking searches are restricted to authoritative German sources:
- Government: destatis.de, bundesnetzagentur.de, bmwk.de
- Research: diw.de, ifo.de, fraunhofer.de
- Fact-checkers: correctiv.org
- EU: ec.europa.eu

See `backend/services/fact_checker.py` for the full list.

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
| `GEMINI_MODEL_CLAIM_EXTRACTION` | Model for claim extraction (default: gemini-2.5-flash) | No |
| `GEMINI_MODEL_FACT_CHECKER` | Model for fact-checking (default: gemini-2.5-pro) | No |
| `FACT_CHECK_PARALLEL` | Enable parallel fact-checking (default: false) | No |
| `FACT_CHECK_RECURSION_LIMIT` | Max agent iterations (default: 25, use lower for tests) | No |
| `DEBUG` | Save audio files for debugging | No |

## License

MIT
