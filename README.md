# Live Faktencheck

**Live at [live-faktencheck.de](https://live-faktencheck.de).**

Real-time fact-checking for German TV talk shows and other spoken-word formats. It
streams audio from the browser, transcribes it as it is spoken, picks out verifiable
claims sentence by sentence, and checks them against authoritative German sources — with
the result appearing in the live transcript within seconds.

It runs as a small multi-user app: each show is a **session**, and access is gated by
per-person **access codes**.

## How It Works

```
  Browser mic ── 16 kHz PCM over WebSocket (/api/stream)
        │
        ▼
┌─────────────────────┐
│ Streaming transcript│  AssemblyAI Universal-Streaming (v3), turn by turn,
│                     │  speaker labels (A, B, …) + session keyterms
└──────────┬──────────┘
           ▼   sentence by sentence
┌─────────────────────┐
│     Claim gate      │  Jev per-sentence classifier (CLAIM_GATE=jev) or a
│                     │  Gemini window extractor — no manual approval
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│   Reformulation     │  Gemini: makes the sentence self-contained (uses the last
│                     │  few sentences) and writes 3–5 search queries
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│     Fast check      │  parallel Tavily searches on trusted domains, sources
│                     │  ranked official-first → one Gemini call: verdict + short reason
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  Live transcript    │  claim passages marked in the chat bubbles; hover/click
│                     │  for verdict, reason and sources ("Schnellcheck" badge)
└─────────────────────┘
```

The operator names speakers by clicking a diarization label (or marking a passage) and
picking a guest; names are never guessed automatically. Only the checked claims and their
results are stored; the live transcript itself is not.

→ Code: `backend/services/streaming.py` (session, windowing), `gate.py`,
`fast_fact_checker.py`; prompts in `prompts/claim_reformulation.md` and
`prompts/fast_fact_checker.md`; tuning knobs in [`docs/configuration.md`](docs/configuration.md#live-lane-streaming).

The app is hosted: the backend runs permanently on the project's VPS and the public site
reads the live API, so there is nothing to install to *use* it — you create a session with
the wizard at `/new` (guests, topic, keyterms), unlock with an access code, and press
**◉ Live-Check**. A short interactive guide (*Kurzanleitung*) opens on the session page.
Past sessions are listed under `/beispiele`.

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

Cost-incurring endpoints (creating sessions, live streaming) require an access code — as
an `X-Access-Code` header, or as a query parameter on the `/api/stream` WebSocket; read-only `GET`s stay open so sessions can be shared by
link. Codes are seeded on startup from `ACCESS_CODES`:

```bash
# name:code, comma-separated
ACCESS_CODES=alice:1234,bob:5678
```

The gate is **fail-closed**: if `ACCESS_CODES` is empty, every gated request is rejected —
always configure it before exposing the backend publicly. Live audio is additionally capped
per code by `LIVE_AUDIO_LIMIT_MINUTES`; the stream is refused once the budget is used up.

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
