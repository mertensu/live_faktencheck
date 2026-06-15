# Live Faktencheck

**Live at [live-faktencheck.de](https://live-faktencheck.de).**

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
         ▼
┌───────────────────┐
│ Claim Extraction  │  Gemini via PydanticAI (speaker → claims → selection)
└────────┬──────────┘
         ▼
┌───────────────────┐
│  Human Review     │  Review / Pro UI (approve · edit · discard)
└────────┬──────────┘
         ▼
┌───────────────────┐
│  Fact-Checking    │  PydanticAI agent: Gemini + Tavily (trusted domains),
│                   │  iterative search → typed verdict + self-critique pass
└────────┬──────────┘
         ▼
┌───────────────────┐
│     Display       │  verdict + evidence + sources, live
└───────────────────┘
```

The fact-check agent loops (search Tavily on trusted German domains → decide → respond),
returns a **typed** result (verdict, evidence, sources) so there are no silent parsing
failures, and is capped at `FACT_CHECK_RECURSION_LIMIT` model requests. A separate
self-critique agent then flags low confidence without changing the verdict.

→ Full pipeline details (models, schemas, prompts): [`docs/llm_pipeline.md`](docs/llm_pipeline.md)

The app is hosted: the backend runs permanently on the Hostinger VPS and the public site
reads the live API, so there is nothing to install to *use* it — you open a session
dashboard, unlock with an access code, and record. New sessions are created through the
wizard at `/new`; paste a single quote at `/pruefen` for a one-shot **Quick Check**.

## Running It Yourself

You only need the steps below to develop on the code or self-host your own instance.

**Requirements:** Python 3.11+ with [uv](https://github.com/astral-sh/uv), Node.js 20+ with
[bun](https://bun.sh) (not npm), and — only for a VPS deployment —
[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/).

```bash
git clone https://github.com/mertensu/live_faktencheck.git
cd live_faktencheck

uv sync                              # Python dependencies
cd frontend && bun install && cd ..  # Frontend dependencies
cp .env.example .env                 # then fill in your keys

./start_dev.sh <session-key>         # run backend + frontend locally (no tunnel)
```

Minimum keys to fill in `.env`:

```bash
ASSEMBLYAI_API_KEY=your_key    # Transcription
GEMINI_API_KEY=your_key        # Claim extraction & fact-checking (GOOGLE_API_KEY also works)
TAVILY_API_KEY=your_key        # Web search for fact-checking
ACCESS_CODES=name:code         # Access gate (see below)
```

Then open **http://localhost:3000** and unlock with a code. See the
[full environment-variable reference](docs/configuration.md) for tuning models, concurrency,
audio limits, and observability, and [docs/live-workflow.md](docs/live-workflow.md),
[docs/development-workflow.md](docs/development-workflow.md), and
[docs/deployment.md](docs/deployment.md) for the workflows.

## Access Codes

Cost-incurring endpoints (sessions, audio/text, claim approval, fact-checking, Quick Check)
require an `X-Access-Code` header; read-only `GET`s stay open so sessions can be shared by
link. Codes are seeded on startup from `ACCESS_CODES`:

```bash
# name:code  — or  name:code:quick_check_limit  (a number or "unlimited")
ACCESS_CODES=alice:1234,bob:5678:5,owner:9999:unlimited
```

The gate is **fail-closed**: if `ACCESS_CODES` is empty, every gated request is rejected —
always configure it before exposing the backend publicly. Live audio is additionally capped
per code by `LIVE_AUDIO_LIMIT_MINUTES` (returns HTTP 429 when exhausted).

## Trusted Sources

Fact-checking searches are restricted to authoritative German sources, organized by category
(government, research, media, EU, …). See `backend/services/trusted_domains.py`, or visit
`/trusted-domains` on the running frontend.

## Database

All sessions and fact-checks live in `backend/data/factcheck.db` (SQLite), the single source
of truth. It is **not** committed to git; the VPS holds the authoritative copy and the
backend runs as a single process. See [`docs/deployment.md`](docs/deployment.md) for backups.

## Adapting to Another Language

LLM field descriptions live in `backend/lang.py`. To run the system in a language other than
German, see [`docs/language-adaptation.md`](docs/language-adaptation.md).

## Contributing

Contributions are welcome — open an issue or pull request. For questions, contributing, or
commercial licensing, reach out at [info@live-faktencheck.de](mailto:info@live-faktencheck.de).

## License

Source-available under [PolyForm Noncommercial 1.0.0](LICENSE). Noncommercial use is
permitted; for commercial use, please get in touch at
[info@live-faktencheck.de](mailto:info@live-faktencheck.de).
