# Live Faktencheck

Real-time fact-checking for German TV talk shows and other spoken-word formats. It
captures audio in the browser, transcribes it, extracts verifiable claims, and verifies
them against authoritative German sources — with results shown live in a dashboard.

It runs as a small multi-user app: each fact-check run is a **session**, access is gated
by per-person **access codes**, and there is a lightweight one-shot **Quick Check** for
pasting a single quote without recording any audio.

## How It Works

```
  Browser mic (fixed-length blocks)
        │
        ▼
┌───────────────────┐
│   Transcription   │  AssemblyAI (universal-3-pro, speaker diarization)
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│ Claim Extraction  │  Gemini via PydanticAI
│                   │  (speaker → claims → selection)
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  Human Review     │  Review / Pro UI (approve · edit · discard)
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│  Fact-Checking    │  PydanticAI agent
│  ┌─────────────┐  │  (Gemini + Tavily search, trusted domains only)
│  │Reason→Search│  │  + separate self-critique pass
│  │  →Evaluate  │  │
│  └──────↺──────┘  │
└────────┬──────────┘
         │
         ▼
┌───────────────────┐
│     Display       │  verdict + evidence + sources
└───────────────────┘
```

1. **Audio Capture** — the browser mic recorder records audio in fixed-length blocks and posts them to the backend (no local listener process).
2. **Transcription** — AssemblyAI (`universal-3-pro`, falling back to `universal-2`) transcribes with speaker diarization; participant names are passed as keyterms to lock in proper nouns.
3. **Claim Extraction** — Gemini (via PydanticAI) resolves speakers, extracts verifiable factual claims, and selects the ones worth checking.
4. **Human Review** — the dashboard offers a mobile-friendly **Review** mode (swipe to approve/discard) and a **Pro** mode (full admin view); optional **Auto** mode checks claims without manual review.
5. **Fact-Checking** — a PydanticAI agent iteratively searches with Tavily (restricted to trusted German domains), returns a consistency verdict with evidence and sources, then a separate self-critique agent annotates confidence without overriding the verdict.
6. **Display** — verdicts, evidence, and sources are rendered live; the public site reads the live API.

For VPS deployment details, see [`docs/deployment.md`](docs/deployment.md).
For the LLM pipeline (models, schemas, prompts), see [`docs/llm_pipeline.md`](docs/llm_pipeline.md).

## Requirements

- Python 3.11+
- Node.js 20+ (use [bun](https://bun.sh), not npm)
- [uv](https://github.com/astral-sh/uv) (Python package manager)
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/) (Cloudflare Tunnel, for the VPS deployment)

## Installation

```bash
# Clone the repo
git clone https://github.com/mertensu/live_faktencheck.git
cd live_faktencheck

# Install Python dependencies
uv sync

# Install frontend dependencies
cd frontend && bun install && cd ..

# Copy the env template and add your keys
cp .env.example .env
```

Minimum keys to fill in `.env`:

```bash
ASSEMBLYAI_API_KEY=your_key    # Transcription
GEMINI_API_KEY=your_key        # Claim extraction & fact-checking (GOOGLE_API_KEY also works)
TAVILY_API_KEY=your_key        # Web search for fact-checking
ACCESS_CODES=name:code         # Access gate (see "Access Codes" below)
```

## Access Codes

Cost-incurring endpoints (creating sessions, posting audio/text, approving claims,
fact-checking, Quick Check) are gated by an access code sent as the `X-Access-Code`
header. Codes are seeded into the SQLite `codes` table on startup from the `ACCESS_CODES`
env var:

```bash
# name:code  — or  name:code:quick_check_limit  (limit = a number or "unlimited")
ACCESS_CODES=alice:1234,bob:5678:5,owner:9999:unlimited
```

- Read-only `GET` endpoints stay open (sessions are shared via link).
- The gate is **fail-closed**: if `ACCESS_CODES` is empty, every gated request is rejected. Always configure it before exposing the backend publicly.
- `quick_check_limit` caps lifetime Quick Checks per code (`unlimited` exempts owners); it defaults to a small cap when omitted.
- Live audio is additionally capped per code by `LIVE_AUDIO_LIMIT_MINUTES` (see Environment Variables). When the budget is exhausted the recorder stops and the API returns HTTP 429.

## Workflows

### Live Fact-Check (on air)

The backend runs permanently on the Hostinger VPS. Open a session dashboard, unlock with
your access code, and use **Review** mode (or switch to **Pro**) — click "Aufnahme starten"
to begin capturing audio via the browser mic recorder. New sessions are created through the
setup wizard at `/new`. See [docs/live-workflow.md](docs/live-workflow.md) and
[docs/deployment.md](docs/deployment.md).

### Quick Check (no audio)

Paste a single quote at `/pruefen`; it runs synchronously through the same fact-checker and
returns one result card. Gated by access code and a per-code lifetime quota.

### Development / Testing

```bash
./start_dev.sh <session-key>
```

Then open the UI at **http://localhost:3000**, unlock with a code, and start the recorder.
→ Full details: [docs/development-workflow.md](docs/development-workflow.md)

## Database

All sessions and fact-checks are stored in `backend/data/factcheck.db` (SQLite), the single
source of truth. The database is **not** committed to git; the VPS holds the authoritative
copy. Because state is held per-process, the backend runs as a single process. See
[`docs/deployment.md`](docs/deployment.md) for backup instructions.

## Project Structure

```
├── backend/
│   ├── app.py                  # FastAPI app (routers, CORS, lifespan)
│   ├── auth.py                 # Access-code gate + seeding + audio budget
│   ├── routers/                # sessions, audio, claims, fact_checks, config, pipeline
│   ├── data/
│   │   └── factcheck.db        # SQLite database (not in git)
│   ├── lang.py                 # German LLM field descriptions (change to adapt language)
│   └── services/
│       ├── transcription.py    # AssemblyAI (universal-3-pro + keyterms)
│       ├── claim_extraction.py # Gemini claim extraction (PydanticAI, 3 agents)
│       ├── fact_checker.py     # PydanticAI agent (Gemini + Tavily) + self-critique
│       ├── search.py           # Tavily search tool (trusted-domain filtered)
│       ├── observability.py    # Logfire setup (no-op without LOGFIRE_TOKEN)
│       └── trusted_domains.py  # Trusted source domains (categorized)
├── frontend/
│   └── src/                    # React app (HomePage, wizard, FactCheckPage, …)
├── prompts/                    # claim_extraction.md, fact_checker.md, self_critique.md, …
├── deploy/
│   ├── factcheck-backend.service  # systemd service for the VPS
│   ├── cloudflared-config.yml     # Cloudflare tunnel config
│   └── deploy.sh                  # Update the deployed backend on the VPS
├── config.py                   # Legacy episode configuration (EPISODES dict)
└── start_dev.sh                # Development startup (backend + frontend, no tunnel)
```

## Trusted Sources

Fact-checking searches are restricted to authoritative German sources, organized by
category (government, research, media, EU, etc.). See
`backend/services/trusted_domains.py`, or visit `/trusted-domains` on the running frontend.

## How Fact-Checking Works

The fact-checker is a [PydanticAI](https://ai.pydantic.dev) agent with a Tavily search tool:

```
┌─────────────────────────────────────────────────────────────┐
│                     Fact-Check Agent Loop                   │
├─────────────────────────────────────────────────────────────┤
│  1. Agent receives the claim + speaker + context            │
│  2. Agent decides: search for more evidence OR respond      │
│  3. If search: Tavily (trusted domains only) → repeat       │
│  4. If respond: typed verdict + evidence + sources          │
│  5. Separate self-critique agent annotates confidence       │
└─────────────────────────────────────────────────────────────┘
```

- **Typed output** — the agent returns a structured result (consistency verdict, evidence, sources), so there are no silent parsing failures.
- **Request limit** — capped at `FACT_CHECK_RECURSION_LIMIT` model requests (default 35) to prevent runaway loops.
- **Model fallback** — if the primary model is unavailable, it falls back to `gemini-3-flash-preview`.
- **Self-critique** — a separate agent reviews the verdict and flags low confidence (`double_check` / `critique_note`) without changing or gating the verdict. Disable with `SELF_CRITIQUE_ENABLED=false`.
- **Observability** — when `LOGFIRE_TOKEN` is set, full traces are sent to [Logfire](https://logfire.pydantic.dev); it is a no-op otherwise.

## Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `ASSEMBLYAI_API_KEY` | AssemblyAI key for transcription | Yes | — |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Google Gemini key | Yes | — |
| `TAVILY_API_KEY` | Tavily key for web search | Yes | — |
| `ACCESS_CODES` | Access-code seeds, `name:code[:limit]` (gate is fail-closed) | Yes (for a gated/public backend) | — |
| `LIVE_AUDIO_LIMIT_MINUTES` | Per-code lifetime live-audio budget (minutes) | No | `5` |
| `ASSEMBLYAI_SPEECH_MODELS` | Comma-separated model preference (rollback knob) | No | `universal-3-pro,universal-2` |
| `GEMINI_MODEL_CLAIM_EXTRACTION` | Model for claim extraction | No | `gemini-2.5-flash` |
| `GEMINI_MODEL_FACT_CHECKER` | Model for fact-checking | No | `gemini-2.5-pro` |
| `GEMINI_MODEL_FACT_CHECKER_FALLBACK` | Fallback fact-checker model | No | `gemini-3-flash-preview` |
| `GEMINI_MODEL_SELF_CRITIQUE` | Model for the self-critique pass | No | `gemini-2.5-flash` |
| `SELF_CRITIQUE_ENABLED` | Run the self-critique pass | No | `true` |
| `FACT_CHECK_RECURSION_LIMIT` | Max agent model requests per claim | No | `35` |
| `FACT_CHECK_PARALLEL` | Fact-check claims in a batch concurrently | No | `false` |
| `FACT_CHECK_MAX_WORKERS` | Concurrent fact-checks within a batch | No | `5` |
| `FACT_CHECK_MAX_CONCURRENCY` | Concurrent approval batches | No | `2` |
| `TAVILY_SEARCH_DEPTH` | `basic` or `advanced` | No | `basic` |
| `TAVILY_MAX_RESULTS` | Results per search | No | `5` |
| `MAX_AUDIO_BLOCK_BYTES` | Max accepted audio block size | No | `26214400` (25 MB) |
| `AUTO_APPROVE` | Fallback auto-approve when a session has no per-session setting | No | `false` |
| `LOGFIRE_TOKEN` | Enables Logfire tracing when present | No | — |
| `VITE_BACKEND_URL` | Backend URL for the production frontend | No | — |

## Adapting to Another Language

LLM field descriptions live in `backend/lang.py`. To run the system in a language other than
German, see [`docs/language-adaptation.md`](docs/language-adaptation.md).

## License

This project is source-available under the [PolyForm Noncommercial 1.0.0](LICENSE) license.
Noncommercial use is permitted; for commercial use, please get in touch.
