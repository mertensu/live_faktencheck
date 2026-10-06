# LLM Pipeline — the Live Lane

The AI core is a streaming pipeline: audio is transcribed as it is spoken, each few
sentences pass a claim gate, and every claim that gets through is fact-checked with one
round of parallel searches and a single synthesis call. There is no human approval step
and no multi-step research loop: a result has to land while the topic is still on air.

```
Browser mic (16 kHz PCM over WebSocket /api/stream)
        │
        ▼
AssemblyAI Universal-Streaming ─── live transcript, diarization labels (A, B, …)
        │  settled sentences, grouped into small windows
        ▼
[1] Claim gate ─────────────────── is there a verifiable, relevant factual claim?
        │   CLAIM_GATE=extractor (default): one flash-lite call decides and extracts
        │   CLAIM_GATE=jev: Jev scores each sentence, a fast LLM judges the grey zone,
        │   then [1b] reformulates the hits
        ▼
[2] Fast check ─────────────────── parallel Tavily searches → one synthesis call
        │  consistency level + one or two sentences + cited sources
        ▼
fact_checks row (check_depth="fast") ─── marked in the live transcript, result on click
```

Orchestration lives in `backend/services/streaming.py` (`StreamingSession`), the gate in
`backend/services/gate.py`, the LLM agents in `backend/services/claim_extraction.py` and
`backend/services/fast_fact_checker.py`. All tunables are listed in
[configuration.md](configuration.md#live-lane-streaming).

---

## Windowing

Finalized transcript turns are split into sentences. With `STREAM_EARLY_SENTENCES` on,
sentences that have settled inside a still-running turn are gated too, so a long answer
does not hold its first claim back. A window is flushed once it holds
`STREAM_WINDOW_MIN_SENTENCES` sentences or spans `STREAM_WINDOW_MAX_TURNS` turns.

Speakers are never guessed: the transcript carries AssemblyAI's labels, and the operator
assigns names by click. A claim that cannot be tied to a label is stored under "Unklar".

Only claims of a voice the operator gave to a guest go on air (`STREAM_HOLD_UNASSIGNED`).
A clip ("Einspieler") brings many other voices, some of them the guests' own. A claim of a
label nobody has named yet is checked in the background but held back; once the label (or
the marked passage) is given to a guest, it appears with its result. The operator marks a
clip voice as "Andere Stimme – nicht prüfen": that label is no longer gated, and claims
already published from it from that turn on are withdrawn (deleted, `claim_withdrawn`).
Correcting it back publishes them again without a second check.

---

## Call 1 — Claim gate

Two implementations sit behind the `ClaimGate` protocol, chosen by `CLAIM_GATE`.

### `extractor` (default) — window gate

**Prompt:** `prompts/claim_extraction_streaming.md`
**Schema:** `ClaimExtractionInput`
**Model:** `GEMINI_MODEL_WINDOW_GATE` (default `gemini-3.5-flash-lite`)
**Output:** `ClaimList` — zero or more `(name, claim)` pairs

```
ClaimExtractionInput
├── conversation_type:     str        # "debate" | "interview" | "private"
├── guests:                list[str]  # ["Caren Miosga (Moderatorin)", "Heidi Reichinnek (Linke)"]
├── context:               str        # thematic background of the session
├── excluded_speakers:     list[str]  # e.g. the host — their statements are not extracted
├── transcript:            str        # the window (a few sentences)
└── previous_block_ending: str | None # preceding sentences, only to resolve references
```

One cheap call both decides whether the window contains a checkable claim and rewrites it
as a standalone, decontextualized sentence. An empty list is the normal answer.

### `jev` — per-sentence decision + reformulation

Only active when `REQUESTY_API_KEY` is set; otherwise the extractor gate is used.

**Step 1a — Jev** (TypeSafe's calibrated decision model via Requesty) scores every
sentence for *checkability* and *importance*. Sentences above `JEV_CHECK_THRESHOLD` (and
`JEV_IMPORTANCE_THRESHOLD`) pass; below `JEV_SKIP_THRESHOLD` they are dropped. See
`benchmarks/jev_gate_bench.py`.

**Step 1a' — grey zone.** Claims in a debate are often wrapped in an assessment ("Der Staat
nimmt den Bürgern immer mehr Geld weg"), which Jev scores around 0.5. A sentence that is
not a hit, with check ≥ `JEV_SKIP_THRESHOLD` and importance ≥
`JEV_GREY_IMPORTANCE_THRESHOLD`, goes to `GEMINI_MODEL_GREY_ZONE` (prompt
`prompts/claim_grey_zone.md`, output `check_worthy: bool`) for a second opinion; on yes it
is reformulated like a hit. Grey sentences are judged in parallel with the
reformulation of the hits; a window's claims arrive once its slowest sentence is done
(≈ +0.5 s). See `benchmarks/grey_zone_bench.py`.

**Step 1b — Reformulation**

**Prompt:** `prompts/claim_reformulation.md`
**Schema:** `ReformulationInput`
**Model:** `GEMINI_MODEL_REFORMULATE` (default `gpt-6-luna@eu` via Requesty, reasoning `medium`)
**Output:** `ReformulatedClaim` — `(name, claim, search_queries)`

```
ReformulationInput
├── sentence:         str        # the sentence Jev let through
├── speaker:          str        # diarization label or assigned name
├── guests:           list[str]
├── context:          str
└── previous_context: str | None # REFORMULATE_CONTEXT_SENTENCES preceding sentences
```

The reformulator does **not** judge check-worthiness — Jev already did. It resolves
pronouns, keeps the speaker out of the claim text, and writes exactly five short German
search queries, each from a different angle (claim, data source, study, yardstick, and a
neutral development/counter-position query without the claim's number). The study query
always starts with „Studie“: the deciding number often sits in one particular study. For
comparisons with other countries, the EU or internationally, the yardstick query is written
in English: Eurostat, OECD and IEA publish in English, and German queries never surfaced them. Those queries decide what the fast check gets to see: covering the topic broadly
made verdicts stable across runs, where near-identical rewordings used to flip them.

**Why two steps?** Jev is cheaper per sentence and better calibrated than the flash-lite
window gate, which in benchmarking was too conservative. The expensive LLM only runs on
the hits.

---

## Call 2 — Fast check

**Prompt:** `prompts/fast_fact_checker.md`
**Model:** `GEMINI_MODEL_FAST_CHECK` (default `vertex/gemini-3.8-flash@eu` via Requesty, thinking `low`)
**Output:** `FastVerdict` — `evidence`, `consistency`, `sources`

The rules for each output field — what the four levels mean (including: a claimed cause
needs evidence of its own), how to cite — live only in the field descriptions in
`backend/lang.py`, sent with the output schema. The prompt keeps just the role, the
guardrails and how to match evidence to the claim (subject, time, rounding, source weight).

1. **Search.** Up to `FAST_SEARCH_MAX_QUERIES` Tavily searches run **in parallel**
   (depth `FAST_TAVILY_SEARCH_DEPTH`), restricted to the trusted domains in
   `backend/services/trusted_domains.py`. Queries come from the reformulator; without
   them, heuristic variants of the claim are used.
2. **Filter and rank.** Hits are de-duplicated by URL, bare homepages and plenary
   transcripts are dropped, and the rest are sorted by source tier: federal/EU official
   sources, then research institutes and fact-checkers, then state (Länder) sources, then
   parties. Press is not on the trusted list: checks never cite newspapers or broadcasters.
3. **Synthesize.** One call gets the claim, speaker, session context and date plus the
   ranked snippets (`FAST_SNIPPET_CHARS` each). It writes the finding first and derives
   the level from it:
   - `hoch` — the data supports the claim
   - `niedrig` — the data contradicts the claim
   - `unklar` — conflicting evidence without a clear direction
   - `keine Datenlage` — nothing relevant found
4. **Follow named documents.** The verdict also lists up to `FAST_FOLLOW_DOCS_MAX` official
   documents, studies or reports that the hits mention but don't contain (e.g. "Finanzplan
   des Bundes 2025 bis 2029"). Each is searched by its title; up to two new hits per title,
   PDFs first, are read (Tavily Extract, passages matching the claim) and the judge rules
   once more with them. Only runs when a document is named: ~+10 s, 1 credit per title.
5. **Read deeper (only if undecided).** If the level is `unklar` or `keine Datenlage`, the
   check reads inside the documents it already found: Tavily Extract returns the passages
   matching the claim from up to `FAST_EXTRACT_MAX_URLS` PDFs and research hits, and the same
   call rules once more with those passages added. No new search; ~3 s plus the second call,
   1 Tavily credit per 5 documents. Seen: a Bundestag paper whose snippet held only the
   recipient count, while the expenditure sat further inside.
6. **Guard.** Only sources whose URL was actually among the search results are kept, so
   invented or mangled links never reach the page. On any failure the check returns
   `unklar` with the error, never raising into the stream.

The model is never allowed to judge a person or give absolute verdicts ("wahr",
"falsch"); it rates how well the claim is backed by data.

---

## Fallbacks

Every model call goes through `build_model()` in `backend/services/llm_base.py`: primary
model → second Gemini model (always Google `gemini-3.6-flash` behind a Requesty primary) →
Claude via Requesty (EU) when `REQUESTY_API_KEY` is set. See [configuration.md](configuration.md#cross-provider-fallback).

---

## Stored results

Each check is one row in `fact_checks` with `check_depth="fast"`, written first as a
`processing` placeholder (so the mark appears in the transcript immediately) and then
updated in place. Older rows with `check_depth="deep"` — the examples under `/beispiele` —
come from the ReAct deep checker with self-critique, removed in v0.3.0 (the code is still
in tag `v0.2.0`; `v0.1.0` is the last release that used it). They are displayed unchanged, including their `double_check` flag
and `critique_note`.
