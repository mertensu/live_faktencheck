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
| `TAVILY_SEARCH_DEPTH` | Pins the depth (`fast`/`advanced`), overriding the agent's per-query choice. Leave empty to let the agent decide; set it as a kill-switch or for benchmarks | — |
| `TAVILY_MAX_RESULTS` | Results per search | `5` |
| `AUTO_APPROVE` | Fallback auto-approve when a session has no per-session setting | `false` |

## Cross-provider fallback

To survive a full Google outage (downtime, quota, auth) mid-broadcast, `build_model()` in
`backend/services/llm_base.py` appends a **non-Google** model as the last tier — Claude via
Requesty, EU-hosted. Both the fact-checker and claim extraction run
`gemini-2.5-pro → claude-opus-4-8@eu`.

It engages only when `REQUESTY_API_KEY` is set; without it the pipeline runs Google-only
and stays fully functional. That is why `.env.example` leaves the key commented out — a
placeholder value would switch the fallback *on* with a key that cannot work, turning a
Google hiccup into a confusing auth error.

| Variable | Description | Default |
|----------|-------------|---------|
| `REQUESTY_API_KEY` | Enables the fallback when present | — |
| `PROVIDER_FALLBACK_ENABLED` | `false` disables the tier entirely | `true` |
| `PROVIDER_FALLBACK_MODEL` | Requesty **router** across EU backends — more redundancy than one pinned provider | `claude-opus-4-8@eu` |
| `REQUESTY_BASE_URL` | Requesty endpoint | `https://router.requesty.ai/v1` |

Production leaves `GEMINI_MODEL_FACT_CHECKER_FALLBACK` **empty** on purpose: it skips the
weak Gemini-Flash intermediate step so the fact-checker falls straight through to the
cross-provider tier.

## Observability & frontend

| Variable | Description | Default |
|----------|-------------|---------|
| `LOGFIRE_TOKEN` | Enables Logfire tracing when present | — |
| `VITE_BACKEND_URL` | Backend URL for the production frontend | — |
