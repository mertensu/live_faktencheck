# Live Faktencheck

Real-time fact-checking system for German TV talk shows. Captures audio, extracts claims, and verifies them against authoritative sources.

## How It Works

```
  Live Audio Stream
        │ (fixed-length blocks)
        ▼
┌───────────────────┐
│   Transcription   │  AssemblyAI (speaker detection)
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ Claim Extraction  │  Gemini LLM
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  Human Review     │  Admin UI (approve / discard)
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  Fact-Checking    │  LangChain ReAct agent
│  ┌─────────────┐  │  (Gemini + Tavily search)
│  │Reason→Search│  │
│  │  →Evaluate  │  │
│  └──────↺──────┘  │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│     Display       │  verdict + explanation + sources
└───────────────────┘
```

1. **Audio Capture**: Listener captures audio via BlackHole virtual audio device
2. **Transcription**: AssemblyAI transcribes with speaker detection
3. **Claim Extraction**: Gemini extracts verifiable factual claims
4. **Human Review**: Admin UI allows editing and approval of claims
5. **Fact-Checking**: LangChain agent with Gemini + Tavily verifies claims against trusted German sources
6. **Display**: Results shown on Cloudflare Pages (public) and local admin UI

For VPS deployment details, see [`docs/deployment.md`](docs/deployment.md).

For details on the LLM pipeline (models, schemas, prompts): [`docs/llm_pipeline.md`](docs/llm_pipeline.md)

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

The backend runs permanently on the Hostinger VPS. Start the listener locally and use the live admin UI. See [docs/live-workflow.md](docs/live-workflow.md) and [docs/deployment.md](docs/deployment.md).

---

### Development / Testing

```bash
./start_dev.sh <episode-key>
uv run python listener.py <episode-key>
```

→ Full details: [docs/development-workflow.md](docs/development-workflow.md)

## Database

All fact-checks are stored in `backend/data/factcheck.db` (SQLite). This is the single source of truth. The database is **not** committed to git; the VPS holds the authoritative copy. See [`docs/deployment.md`](docs/deployment.md) for backup instructions.

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
│   └── src/App.jsx            # React frontend
├── prompts/
│   ├── claim_extraction.md    # Prompt for extracting claims
│   ├── fact_checker.md        # Prompt for fact-checking
│   └── lang_de.toml           # LLM field descriptions (German)
├── deploy/
│   ├── factcheck-backend.service  # systemd service for the VPS
│   ├── cloudflared-config.yml     # Cloudflare tunnel config
│   └── deploy.sh                  # Update the deployed backend on the VPS
├── listener.py                # Audio capture with fixed-interval sending
├── config.py                  # Episode configuration (EPISODES dict)
└── start_dev.sh               # Development startup (backend + frontend, no tunnel)
```

## Configuration

Episodes are configured in `config.py` using the `Episode` dataclass. The `publish` flag controls visibility on the live API (unpublished episodes are filtered out of the public endpoint):

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
        publish=True,   # visible on live-faktencheck.de via the live API
    )
}
```

Available fields:
- `show` — key into `SHOWS` dict (e.g. `"maischberger"`, `"lanz"`)
- `date` — broadcast date string (e.g. `"19. September 2025"`)
- `guests` — list of `"Name (Role/Partei)"` strings; moderator first
- `context` — optional background context passed to the LLM
- `reference_links` — optional list of reference URLs (legislation, press releases)
- `publish` — `True` = visible via the live API on production domain (default: `False`)
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

## Adapting to Another Language

To run the system in a language other than German, see [`docs/language-adaptation.md`](docs/language-adaptation.md).

## License

MIT
