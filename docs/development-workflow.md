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
./start_dev.sh atalay-2026-02-09   # an episode from backend/config.py (speakers, context)
```

Open **http://localhost:3000/atalay-2026-02-09**, unlock with an access code, and click
**◉ Live-Check** in the header to stream the browser mic. Claims are gated and checked
automatically and appear as marks in the live transcript. Sessions created in the wizard
(**/new**) work the same way.

Results are visible locally only — nothing appears on the public domain. Stop with Ctrl-C
or kill the backend/frontend processes.

---

## Tests, lint, build

```bash
uv run pytest backend/tests          # backend unit tests (no API keys, no network)
uv run ruff check backend/           # lint
cd frontend && bun run test          # frontend unit tests (vitest)
cd frontend && bun run build         # must pass before committing frontend changes
```

The backend tests mock every model (`ALLOW_MODEL_REQUESTS=False`), so an accidental real
LLM call fails loudly. Real-API measurements live in `benchmarks/`, not in the test suite.
