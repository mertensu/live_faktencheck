# Spec — Agent Rewrite: LangChain → PydanticAI + Logfire (Phase R)

**Date:** 2026-06-10
**Branch:** `worktree-session-multitenancy` (Worktree: `.claude/worktrees/session-multitenancy`)
**Status:** Designed — ready for implementation plan.

## Problem

The fact-checking pipeline mixes two LLM idioms. The **fact-checker** (`fact_checker.py`)
runs on LangChain/LangGraph (`create_agent` ReAct loop, `ChatGoogleGenerativeAI` with
`with_fallbacks`, `TavilySearch`). The **extraction** stage (`claim_extraction.py` — speaker
resolution + claim extraction) and the **self-critique** step both call `google-genai`
directly. This produces:

- A heavy dependency tree (`langchain`, `langchain-google-genai`, `langchain-tavily`,
  `langgraph`, `langgraph-cli`) for what is, agentically, a single tool-calling loop.
- Reliability band-aids in `fact_checker.py`: sync-in-thread to dodge `ainvoke` bugs,
  manual `structured_response` unwrapping, retry-on-empty-fields when Gemini ignores
  `tool_choice`, and recursion-trace file dumps.
- Fragmented observability: ad-hoc first-prompt dumps, recursion-trace files, and a custom
  `CostTracker` writing `cost_history.json` — no unified trace of an agent run.
- Three different call styles across four LLM steps, with no shared model/fallback config.

This rewrite moves the **entire LLM layer** onto **PydanticAI** (typed Agents, tools,
structured output) with **Logfire** for observability, on a shared model foundation. It is
sequenced **before Phase Q** (Quick Check) because Q reuses the `fact_checker` service —
migrating first avoids building Q on LangChain and re-migrating both later.

## Goals

Driven by (all selected during brainstorming):

1. **Simpler, lighter code** — drop the LangChain/LangGraph tree and its workarounds.
2. **Better observability** — Logfire spans for every agent run (requests, tokens, tool
   calls, cost) replacing the dump files + custom CostTracker.
3. **Reliability / control** — PydanticAI's guaranteed typed output removes the
   structured-output hacks; `UsageLimits` cleanly bounds the loop.
4. **Modern foundation for Phase Q** — one coherent idiom to build Quick Check on.

## Scope

**In scope (this pass) — full unification of all four LLM steps:**

- ① Speaker resolution, ② claim extraction, ③ fact-check agent, ④ self-critique all become
  PydanticAI `Agent`s on a shared `GoogleModel` + `FallbackModel` base.
- Logfire instrumentation, opt-in via `send_to_logfire='if-token-present'`.
- Tavily as a native PydanticAI tool via `tavily-python` directly (drop `langchain-tavily`),
  preserving the "retry without date filter on empty result" behavior.
- Rewrite of `fact_checker.py` and `claim_extraction.py`; new `llm_base.py`,
  `observability.py`, `search.py`.
- Removal of `cost_tracker.py`, `studio_graph.py`, `mock_search.py` and the LangChain/
  LangGraph dependencies.
- Test rewrite using PydanticAI `TestModel`/`FunctionModel`.

**Out of scope:**

- Public service APIs and the `registry` accessors — **unchanged** (see Constraints).
- Routers (`audio.py`, `claims.py`, `fact_checks.py`), the prompts in `prompts/`, the
  Pydantic output models (`FactCheckResponse`, `Source`, `SelfCritiqueResponse`,
  `ClaimInput`, `ClaimList`, `ResolvedTranscript`, …), and `backend/lang.py` field
  descriptions.
- Phase Q (Quick Check) and Phase 3b (Live-Limits) — separate specs.
- Any change to the AssemblyAI transcription service.

## Constraints / Invariants

- **Public service APIs stay identical.** `ClaimExtractor.resolve_labels_async` /
  `extract_claims_async`, `FactChecker.check_claim(s)_async` (+ sync wrappers), and
  `registry.get_claim_extractor` / `get_fact_checker` keep their signatures and return
  shapes (dicts/lists as today). The entire blast radius stays inside `backend/services/`;
  routers are untouched.
- **No behavior change to self-critique semantics.** It annotates the result
  (`double_check`, `critique_note`); it never blocks or retries the verdict.
- **Logfire is never a hard runtime dependency.** Unconfigured (no `LOGFIRE_TOKEN`) it is a
  silent no-op, so the VPS keeps running without an account.
- **Fact-check loop behavior is preserved** — the LangGraph `create_agent` ReAct loop and
  PydanticAI's tool-calling loop are the same reason→act→observe cycle via native function
  calls; this is a mechanism swap, not a behavior change.

## Architecture

New shared foundation; each LLM step is a typed `Agent`. Single-shot steps (①②④) have no
tools, so their "loop" is one model call → typed output. Only ③ (fact-check) has a tool and
actually loops.

```
backend/services/
  llm_base.py        NEW — build_model() -> GoogleModel + FallbackModel,
                     GoogleModelSettings(temperature=0). Reads GEMINI_MODEL_* + API key from
                     env in one place. Provider: GoogleProvider(api_key=...).
  observability.py   NEW — configure_logfire() called once at FastAPI startup:
                       logfire.configure(send_to_logfire='if-token-present')
                       logfire.instrument_pydantic_ai()
                     No-op when LOGFIRE_TOKEN is absent.
  search.py          NEW — tavily_search PydanticAI tool (async) using tavily-python directly.
                     include_domains=TRUSTED_DOMAINS, max_results/search_depth from env.
                     Preserves: empty result WITH a date filter -> retry WITHOUT it.
  claim_extraction.py  REWRITTEN — speaker_resolver Agent[ResolvedTranscript] +
                       claim_extractor Agent[ClaimList]. Same public methods, prompts,
                       schemas, and the existing claim_selection step.
  fact_checker.py      REWRITTEN — fact_check Agent[FactCheckResponse] (tavily tool, loops) +
                       self_critique Agent[SelfCritiqueResponse]. Same public methods,
                       parallel/sequential orchestration, graceful error fallback.
  cost_tracker.py    DELETED   (no HTTP consumers; Logfire owns cost/usage)
  studio_graph.py    DELETED   (Logfire replaces Studio tracing)
  mock_search.py     DELETED   (tests use TestModel/FunctionModel + tool override)
```

**Dependencies** — remove: `langchain`, `langchain-google-genai`, `langchain-tavily`,
`langgraph`, `langgraph-cli`. Add: `pydantic-ai`, `logfire`. Keep: `google-genai` (still used
elsewhere), `tavily-python`.

### The four agents

**① Speaker resolver** — `Agent(model, output_type=ResolvedTranscript, instructions=...)`,
no tools. `resolve_labels_async` runs it, then applies label→name replacements to the
transcript (unchanged post-processing).

**② Claim extractor** — `Agent(model, output_type=ClaimList, instructions=...)`, no tools.
Existing `claim_selection.md` step retained.

**③ Fact-check agent** — the only agentic step:
```python
Agent(model, output_type=FactCheckResponse, tools=[tavily_search],
      instructions=baked_prompt, retries=2)
result = await agent.run(user_message, usage_limits=UsageLimits(request_limit=N))
```
- `{input_schema}` / `{current_date}` prompt baking preserved (injected into instructions).
- `N` maps from today's `FACT_CHECK_RECURSION_LIMIT`.
- PydanticAI guarantees a typed `FactCheckResponse`, so the structured-output hacks
  (`structured_response` unwrapping, plain-text retry, empty-field fallback) are **removed**.
- On `UsageLimitExceeded`: one retry, then graceful fallback to
  `consistency="unklar"` with an error `evidence` string (same degradation as today's
  `except`).

**④ Self-critique** — a **separate annotating agent**, NOT an `output_validator`:
```python
Agent(critique_model, output_type=SelfCritiqueResponse, instructions=...)
```
Rationale: critique only sets `double_check` / `critique_note` for the UI; it must never
gate or retry the verdict, which is what an `output_validator` would do. Kept behind
`SELF_CRITIQUE_ENABLED`, on its own cheaper model. Agent-delegation (critique as a tool of
③) is rejected — it would consume ③'s usage budget and entangle traces.

**Tavily tool (`search.py`)** — async PydanticAI tool calling `tavily-python` directly with
`include_domains=TRUSTED_DOMAINS`. The `FallbackSearchTool` retry logic (empty result with a
date filter → retry without it) moves inside this function. `MOCK_SEARCH` / `mock_search.py`
removed.

## Data flow (unchanged at the seams)

```
audio block  -> ClaimExtractor.resolve_labels_async -> extract_claims_async -> pending claims
                                                                    |
                                                          (human admin review)
                                                                    v
approved claims -> FactChecker.check_claims_async -> [per claim: ③ fact-check loop -> ④ critique]
                -> list[dict]  (speaker, original_claim, consistency, evidence, sources,
                                double_check, critique_note)
```

The human-in-the-loop admin review between extraction and fact-checking means there is no
single end-to-end agent; "single agent feel" is delivered as **one shared PydanticAI +
Logfire foundation**, not one mega-agent.

## Observability (Logfire)

- `configure_logfire()` called once at FastAPI startup.
- `send_to_logfire='if-token-present'` → silent no-op without `LOGFIRE_TOKEN`.
- `instrument_pydantic_ai()` auto-captures per-run spans: requests, input/output tokens,
  tool calls, and cost (via `genai-prices`).
- Replaces **all** of: first-prompt dump files, recursion-trace dumps, and CostTracker's
  console cost lines + `cost_history.json`.
- **Tradeoff (accepted):** production cost visibility now requires a `LOGFIRE_TOKEN` on the
  VPS. If lightweight local USD logging is ever wanted back, it can be derived from
  `result.usage()` (PydanticAI + genai-prices) without the SaaS — out of scope here.

## Parallelism (unchanged)

The `asyncio.Semaphore` sequential/parallel orchestration (`FACT_CHECK_PARALLEL`,
`FACT_CHECK_MAX_WORKERS`) is retained; it now wraps `agent.run()` per claim. Each claim run
gets its own Logfire span automatically.

## Error handling

- Fact-check: `UsageLimitExceeded` → one retry → graceful `consistency="unklar"` result.
  Any other exception → same graceful error dict as today.
- Self-critique failure → defaults to `confidence="high"` (no `double_check`), as today.
- Tavily failure after the no-date-filter retry → propagates as a tool error the agent can
  reason about (preserving today's `handle_tool_error` intent).

## Testing

- Replace LangChain mocks + `MOCK_SEARCH` with PydanticAI `TestModel` / `FunctionModel` and
  `agent.override(model=...)`. Tool behavior exercised by overriding `tavily_search`.
- Rewrite `test_fact_checker.py`; delete `test_cost_tracker.py`; update conftest mocks.
- Integration tests (real keys) stay `@pytest.mark.integration` and are the **final gate**.
- Acceptance: unit suite green on TestModel; integration run green; **spot-check a known
  episode's fact-checks against current production output** before declaring done.

## Environment variables

**Kept:** `GEMINI_MODEL_FACT_CHECKER`, `GEMINI_MODEL_FACT_CHECKER_FALLBACK`,
`GEMINI_MODEL_CLAIM_EXTRACTION`, `GEMINI_MODEL_SELF_CRITIQUE`, `SELF_CRITIQUE_ENABLED`,
`TAVILY_API_KEY`, `TAVILY_SEARCH_DEPTH`, `TAVILY_MAX_RESULTS`, `FACT_CHECK_PARALLEL`,
`FACT_CHECK_MAX_WORKERS`, `GEMINI_API_KEY` / `GOOGLE_API_KEY`.

**Changed:** `FACT_CHECK_RECURSION_LIMIT` → drives `UsageLimits(request_limit=...)`; env name
kept as an alias so existing `.env` / test configs don't break.

**New:** `LOGFIRE_TOKEN` (optional).

**Removed:** `MOCK_SEARCH`, `LANGSMITH_API_KEY`.

## Risks

- **Core backend logic.** A regression silently degrades fact-check quality. Mitigated by
  the integration gate + production spot-check before merge.
- **Gemini structured output under PydanticAI.** Forcing the final typed output after tool
  calls must work reliably with the Gemini provider; verify in integration tests (this is
  exactly the failure mode the old `tool_choice`/empty-field hack patched).
- **Prompt portability.** Prompts were tuned against LangChain message formatting; verify
  the baked-instructions form yields equivalent behavior during the spot-check.

## Sequencing

Independent of Phases 2 / 3b. Sequenced **before Phase Q**. Self-contained on this branch;
verify against live behavior before merge.
