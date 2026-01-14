# Live Faktencheck

Real-time fact-checking system for German TV talk shows. Captures audio, extracts claims, and verifies them against authoritative sources.

## How It Works

```
Audio Capture → Transcription → Claim Extraction → Human Review → Fact-Checking → Live Display
     │              │                  │                │              │              │
 BlackHole      AssemblyAI         Gemini AI       Admin UI       Gemini +       GitHub
  + VAD                                                           Tavily         Pages
```

1. **Audio Capture**: Listener captures audio via BlackHole virtual audio device
2. **Transcription**: AssemblyAI transcribes with speaker detection
3. **Claim Extraction**: Gemini extracts verifiable factual claims
4. **Human Review**: Admin UI allows editing and approval of claims
5. **Fact-Checking**: Gemini + Tavily search verifies claims against trusted German sources
6. **Display**: Results shown on GitHub Pages (public) and local admin UI

## Requirements

- Python 3.12+
- Node.js 20+
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/) (Cloudflare Tunnel)
- [BlackHole](https://existential.audio/blackhole/) (virtual audio device for macOS)
- [GitHub CLI](https://cli.github.com/) (for automated deployments)

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
cd frontend && npm install && cd ..

# Copy env template and add your API keys
cp .env.example .env
```

## Usage

### Production Mode (Full Pipeline)

```bash
# Start everything: tunnel, backend, frontend
./start_production.sh <episode-key>

# Example
./start_production.sh maischberger-2025-09-19

# In a separate terminal, start the audio listener
uv run python listener.py <episode-key>
```

This will:
- Start Cloudflare Tunnel (exposes backend to internet)
- Update GitHub secret with new tunnel URL
- Trigger GitHub Pages rebuild
- Start backend API
- Start local admin UI at http://localhost:3000

### Development Mode (Backend Only)

```bash
# Start just the backend
./backend/run.sh

# In another terminal, start frontend dev server
cd frontend && npm run dev
```

### Stop Everything

```bash
./stop_production.sh
```

## Project Structure

```
├── backend/
│   ├── app.py                 # Flask API server
│   └── services/
│       ├── transcription.py   # AssemblyAI integration
│       ├── claim_extraction.py # Gemini claim extraction
│       └── fact_checker.py    # Gemini + Tavily fact-checking
├── frontend/
│   ├── src/App.jsx            # React frontend
│   └── public/data/           # Persisted fact-checks (JSON)
├── prompts/
│   ├── claim_extraction.md    # Prompt for extracting claims
│   └── fact_checker.md        # Prompt for fact-checking
├── listener.py                # Audio capture with VAD
├── config.py                  # Episode configuration
├── start_production.sh        # Production startup script
└── stop_production.sh         # Stop all services
```

## Configuration

Episodes are configured in `config.py`:

```python
SHOW_CONFIG = {
    "maischberger-2025-09-19": {
        "name": "Maischberger",
        "speakers": ["Sandra Maischberger", "Gitta Connemann", "Katharina Dröge"],
        "guests": "Description of the episode...",
        "show": "maischberger",
        "episode_name": "19. September 2025"
    }
}
```

## Workflow

1. **Start production** with `./start_production.sh <episode>`
2. **Start listener** with `uv run python listener.py <episode>`
3. **Play audio** through BlackHole (route TV/browser audio)
4. **Review claims** at http://localhost:3000 (Admin Mode)
5. **Approve claims** for fact-checking
6. **View results** on GitHub Pages or local UI

## Trusted Sources

Fact-checking searches are restricted to authoritative German sources:
- Government: destatis.de, bundesnetzagentur.de, bmwk.de
- Research: diw.de, ifo.de, fraunhofer.de
- Fact-checkers: correctiv.org
- EU: ec.europa.eu

See `backend/services/fact_checker.py` for the full list.

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ASSEMBLYAI_API_KEY` | AssemblyAI API key for transcription | Yes |
| `GEMINI_API_KEY` | Google Gemini API key | Yes |
| `TAVILY_API_KEY` | Tavily API key for web search | Yes |
| `GEMINI_MODEL_CLAIM_EXTRACTION` | Model for claim extraction (default: gemini-2.5-flash) | No |
| `GEMINI_MODEL_FACT_CHECKER` | Model for fact-checking (default: gemini-2.5-pro) | No |
| `FACT_CHECK_PARALLEL` | Enable parallel fact-checking (default: false) | No |
| `DEBUG` | Save audio files for debugging | No |

## License

MIT
