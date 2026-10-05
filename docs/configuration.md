# Configuration Reference

All configuration is via environment variables in `.env`. The four required keys are
covered in the [development workflow](development-workflow.md#setup); this is the full list.

## Required

| Variable | Description |
|----------|-------------|
| `ASSEMBLYAI_API_KEY` | AssemblyAI key for transcription |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | Google Gemini key |
| `TAVILY_API_KEY` | Tavily key for web search |
| `ACCESS_CODES` | Access-code seeds, `name:code[:unlimited]`; `unlimited` lifts the live-audio cap (gate is fail-closed; required for a gated/public backend) |

## Transcription

| Variable | Description | Default |
|----------|-------------|---------|
| `ASSEMBLYAI_REGION` | `eu` pins streaming to AssemblyAI's EU endpoint (data residency); unknown values fail when a stream starts | unset (edge routing) |
| `LIVE_AUDIO_LIMIT_MINUTES` | Per-code lifetime live-audio budget (minutes) | `5` |

## Live lane (streaming)

| Variable | Description | Default |
|----------|-------------|---------|
| `STREAM_SPEECH_MODEL` | AssemblyAI streaming model | `universal-3-6-pro` |
| `STREAM_SPEAKER_REVISION_MS` | Interval for AssemblyAI speaker revisions | `120000` |
| `STREAM_MAX_SPEAKERS` | Cap on diarized speakers | unset |
| `STREAM_EARLY_SENTENCES` | Gate settled sentences from partial turns before the turn ends | `true` |
| `STREAM_HOLD_UNASSIGNED` | Publish only claims of voices the operator gave to a guest; others are checked in the background and held (no effect for an episode without a speaker list) | `true` |
| `CLAIM_GATE` | `jev` (per-sentence classifier via Requesty) or `extractor` (Gemini window gate) | `extractor` |
| `GEMINI_MODEL_WINDOW_GATE` | Model for the extractor gate | `gemini-3.5-flash-lite` |
| `JEV_MODEL` / `JEV_TIMEOUT_S` | Jev gate model and per-call timeout (s) | `typesafe/jev-1.13.0` / `5` |
| `JEV_CHECK_THRESHOLD` / `JEV_SKIP_THRESHOLD` | Jev probability band: check above, skip below, grey zone in between | `0.80` / `0.40` |
| `JEV_IMPORTANCE_THRESHOLD` | Minimum Jev importance score | `0.60` |
| `JEV_GREY_ZONE` | Send grey-zone sentences to an LLM for a second opinion (off: skip them) | `true` |
| `JEV_GREY_IMPORTANCE_THRESHOLD` | Minimum Jev importance score for the grey zone | `0.40` |
| `GEMINI_MODEL_GREY_ZONE` / `GEMINI_THINKING_GREY_ZONE` | Grey-zone judge model + thinking level | `gemini-3.5-flash-lite` / `low` |
| `JEV_GATE_DEBUG` | Log per-sentence Jev scores | off |
| `GEMINI_MODEL_REFORMULATE` / `GEMINI_THINKING_REFORMULATE` | Reformulator model + thinking level | `gpt-6-luna@eu` / `medium` |
| `REFORMULATE_CONTEXT_SENTENCES` | Preceding sentences the reformulator sees | `4` |
| `GEMINI_MODEL_FAST_CHECK` / `GEMINI_THINKING_FAST_CHECK` | Fast-check synthesis model + thinking level | `vertex/gemini-3.8-flash@eu` / `low` |
| `GEMINI_MODEL_FACT_CHECKER_FALLBACK` | Second Gemini model for the fast check, tried before the cross-provider tier; empty skips it (behind a Requesty primary, `GOOGLE_FALLBACK_MODEL` is used instead) | `gemini-3-flash-preview` |
| `FAST_SEARCH_MAX_QUERIES` | Parallel Tavily searches per claim | `5` |
| `FAST_TAVILY_SEARCH_DEPTH` | Tavily depth for the fast check | `basic` |
| `FAST_SNIPPET_CHARS` | Characters kept per search hit | `1200` |
| `FAST_EXTRACT` | On `unklar`/`keine Datenlage`, read passages inside the PDFs and research hits found (Tavily Extract) and judge again | `true` |
| `FAST_EXTRACT_MAX_URLS` / `FAST_EXTRACT_CHARS` | Documents read per claim / characters kept from each | `10` / `2500` |
| `TAVILY_MAX_RESULTS` | Results per search | `5` |

## Models via Requesty

A model name with a region suffix (`@eu`) runs through Requesty's EU router instead of
Google directly — the live defaults for the reformulator and the fast check do (EU-hosted,
zero retention, not used for training). The thinking level becomes the reasoning effort.
Behind such a primary, `build_model()` always puts a Google model, so a Requesty outage or
a stalled call (≈28 s seen in benchmarks) falls back after `REQUESTY_TIMEOUT_S`. Without
`REQUESTY_API_KEY` the Google model runs directly.

| Variable | Description | Default |
|----------|-------------|---------|
| `REQUESTY_TIMEOUT_S` | Per-call timeout for a Requesty primary before falling back (no retries) | `12` |
| `GOOGLE_FALLBACK_MODEL` | Google model behind a Requesty primary | `gemini-3.6-flash` |

## Cross-provider fallback

To survive a full Google outage (downtime, quota, auth) mid-broadcast, `build_model()` in
`backend/services/llm_base.py` appends a **non-Google** model as the last tier — Claude via
Requesty, EU-hosted. Every Gemini call in the live lane (window gate, reformulator, fast
check) falls through to `claude-opus-4-8@eu` when Google fails.

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
intermediate Gemini step so the fast check falls straight through to the cross-provider
tier. (The name predates the removal of the deep checker; it now only affects the fast
check.)

## Observability & frontend

| Variable | Description | Default |
|----------|-------------|---------|
| `LOGFIRE_TOKEN` | Enables Logfire tracing when present | — |
| `VITE_BACKEND_URL` | Backend URL for the production frontend | — |
