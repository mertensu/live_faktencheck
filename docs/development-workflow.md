# Development Workflow

Test the full pipeline locally — same tools as production, but without the Cloudflare tunnel. Nothing goes live.

---

## Setup

**Requirements:** Python 3.11+ with [uv](https://github.com/astral-sh/uv), Node.js 20+ with
[bun](https://bun.sh) (not npm).

```bash
git clone https://github.com/mertensu/live_faktencheck.git
cd live_faktencheck

uv sync                              # Python dependencies
cd frontend && bun install && cd ..  # Frontend dependencies
cp .env.example .env                 # then fill in your keys
```

Minimum keys in `.env` (full list: [configuration.md](configuration.md)):

```bash
ASSEMBLYAI_API_KEY=your_key    # Transcription
GEMINI_API_KEY=your_key        # LLM calls (GOOGLE_API_KEY also works)
TAVILY_API_KEY=your_key        # Web search
ACCESS_CODES=name:code         # Access gate, comma-separated; fail-closed if empty
```

---

## Running locally

```bash
# Start backend + frontend (no tunnel)
./start_dev.sh atalay-2026-02-09   # inherits Atalay's speakers and config
```

Open the UI at **http://localhost:3000**, unlock with an access code, and (in **Review** mode, or switch to **Pro**) click "Aufnahme starten" to start the browser mic recorder.

- Review and approve extracted claims in **Review** or **Pro** mode
- Approve claims → fact-checking runs automatically
- Results visible locally only — nothing appears on the public domain

Stop with Ctrl-C in each terminal.
