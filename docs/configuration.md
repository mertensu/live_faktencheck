# Configuration Reference

All configuration is via environment variables in `.env`. The four required keys are
covered in the [README](../README.md#installation); this is the full list.

## Required

| Variable | Description |
|----------|-------------|
| `ASSEMBLYAI_API_KEY` | AssemblyAI key for transcription |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Google Gemini key |
| `TAVILY_API_KEY` | Tavily key for web search |
| `ACCESS_CODES` | Access-code seeds, `name:code[:limit]` (gate is fail-closed; required for a gated/public backend) |

## Transcription

| Variable | Description | Default |
|----------|-------------|---------|
| `ASSEMBLYAI_SPEECH_MODELS` | Comma-separated model preference (rollback knob) | `universal-3-pro,universal-2` |
| `MAX_AUDIO_BLOCK_BYTES` | Max accepted audio block size | `26214400` (25 MB) |
| `LIVE_AUDIO_LIMIT_MINUTES` | Per-code lifetime live-audio budget (minutes) | `5` |

## Models

| Variable | Description | Default |
|----------|-------------|---------|
| `GEMINI_MODEL_CLAIM_EXTRACTION` | Model for claim extraction | `gemini-2.5-flash` |
| `GEMINI_MODEL_FACT_CHECKER` | Model for fact-checking | `gemini-2.5-pro` |
| `GEMINI_MODEL_FACT_CHECKER_FALLBACK` | Fallback fact-checker model | `gemini-3-flash-preview` |
| `GEMINI_MODEL_SELF_CRITIQUE` | Model for the self-critique pass | `gemini-2.5-flash` |
| `SELF_CRITIQUE_ENABLED` | Run the self-critique pass | `true` |

## Fact-checking behaviour

| Variable | Description | Default |
|----------|-------------|---------|
| `FACT_CHECK_RECURSION_LIMIT` | Max agent model requests per claim | `35` |
| `FACT_CHECK_PARALLEL` | Fact-check claims in a batch concurrently | `false` |
| `FACT_CHECK_MAX_WORKERS` | Concurrent fact-checks within a batch | `5` |
| `FACT_CHECK_MAX_CONCURRENCY` | Concurrent approval batches | `2` |
| `TAVILY_SEARCH_DEPTH` | `basic` or `advanced` | `basic` |
| `TAVILY_MAX_RESULTS` | Results per search | `5` |
| `AUTO_APPROVE` | Fallback auto-approve when a session has no per-session setting | `false` |

## Observability & frontend

| Variable | Description | Default |
|----------|-------------|---------|
| `LOGFIRE_TOKEN` | Enables Logfire tracing when present | — |
| `VITE_BACKEND_URL` | Backend URL for the production frontend | — |
