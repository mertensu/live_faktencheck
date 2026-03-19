# LLM Pipeline — Three Calls, Three Schemas

The AI core of the system consists of three sequential LLM calls, each with a dedicated prompt and input schema. They are strictly separated because they solve fundamentally different problems and require different models, output formats, and failure modes.

```
Transcript (raw, with "Sprecher A / B")
        │
        ▼
[1] Speaker Label Resolution      ← gemini-2.5-flash, structured JSON output
        │  resolved transcript
        ▼
[2] Claim Extraction              ← gemini-2.5-flash, structured JSON output
        │  list of claims
        ▼
   Human Review (Admin UI)
        │  approved claims
        ▼
[3] Fact-Checking (ReAct agent)   ← gemini-2.5-pro, tool-calling loop
        │  fact-check results
        ▼
   Frontend Display
```

---

## Call 1 — Speaker Label Resolution

**Prompt:** `prompts/speaker_labels.md`
**Schema:** `SpeakerLabelsInput`
**Model:** gemini-2.5-flash (fast, cheap)
**Output:** Structured `ResolvedTranscript` — a list of `label → name` mappings

```
SpeakerLabelsInput
├── guests:    list[str]   # ["Caren Miosga (Moderatorin)", "Heidi Reichinnek (Linke)"]
└── transcript: str        # raw transcript with "Sprecher A:", "Sprecher B:" labels
```

AssemblyAI's speaker diarization assigns generic labels (`Sprecher A`, `Sprecher B`) rather than real names. This call resolves them to actual person names by matching conversational cues (direct address, topic alignment, stylistic patterns) against the known guest list.

The output is applied as a simple string replacement on the transcript before it is passed to claim extraction. Only high-confidence mappings are returned; uncertain labels are left as-is.

**Why a separate call?** Speaker resolution and claim extraction are independent reasoning tasks. Mixing them into one prompt would increase complexity and prompt length with no benefit. If resolution fails or the show has named speakers from the start (some formats already include names), this step is simply skipped.

---

## Call 2 — Claim Extraction

**Prompt:** `prompts/claim_extraction.md`
**Schema:** `ClaimExtractionInput`
**Model:** gemini-2.5-flash (fast, cheap)
**Output:** Structured `ClaimList` — a list of `(name, claim)` pairs

```
ClaimExtractionInput
├── date:                 str         # "Oktober 2025"
├── guests:               list[str]   # ["Caren Miosga (Moderatorin)", "Heidi Reichinnek (Linke)"]
├── context:              str         # thematic background, e.g. "CDU und SPD haben sich auf..."
├── transcript:           str         # resolved transcript (speaker names already applied)
└── previous_block_ending: str | None # last lines of the prior audio block, for continuity
```

The prompt instructs the model to extract only verifiable, falsifiable factual claims — concrete numbers, causal assertions, historical facts. Opinions, predictions, and vague statements are excluded. Each extracted claim is attributed to its speaker and de-contextualized: pronoun references (`er`, `sie`, `wir`) are resolved to full names so the claim can stand alone without the transcript.

The prompt also handles compound claims: if a speaker makes multiple independent assertions in one sentence, they are separated into individual checkable units.

**Why a separate call?** Claim extraction must be fast — it happens in real time while the show is airing, before any human has reviewed anything. Using a lighter, cheaper model here keeps latency low. The fact-checking step (Call 3) is far more expensive; claim extraction acts as a filter that reduces the number of claims that reach it.

**`previous_block_ending`** solves a continuity problem: audio is processed in fixed-length blocks, so a claim may span a block boundary. Passing the last few lines of the previous block lets the model resolve references that start mid-sentence at the top of the current block.

---

## Call 3 — Fact-Checking (ReAct Agent)

**Prompt:** `prompts/fact_checker.md`
**Schema:** `ClaimInput`
**Model:** gemini-2.5-pro (most capable)
**Output:** Structured `FactCheckResponse` — consistency rating, evidence summary, cited sources

```
ClaimInput
├── context:    str   # thematic background of the episode
├── sprecher:   str   # "Heidi Reichinnek"
├── sendedatum: str   # "Oktober 2025"
└── behauptung: str   # the claim to verify
```

This is the most complex step. Rather than a single LLM call, it runs a LangGraph ReAct agent loop: the model reasons about the claim, issues Tavily web search queries, evaluates the returned sources, and continues until it has sufficient evidence or hits a recursion limit. Searches are restricted to a curated list of authoritative domains (Destatis, DIW, ifo, Correctiv, etc.).

The agent is instructed to:
- seek original sources rather than news summaries
- actively search for counter-evidence before concluding
- treat statements from interest groups (parties, industry associations) as positions, not evidence
- cross-check data against at least two independent official sources

`context` (the thematic background) helps the model formulate relevant search queries. `sendedatum` anchors the claim temporally, since statistics and policies change over time.

**Why a separate call from extraction?** The fact-checker runs after human review — only approved claims reach it. It uses a more expensive model and an unbounded tool-calling loop, making it unsuitable for the real-time extraction phase. The schema is also structurally different: instead of a transcript, it receives a single resolved claim with all necessary attribution already embedded.

---

## Schema Design Principles

Each schema contains exactly what that LLM call needs — no more.

| Field | Speaker Labels | Claim Extraction | Fact-Checking |
|---|---|---|---|
| `guests` (list) | ✓ (to match labels) | ✓ (for attribution) | — (speaker already resolved) |
| `date` | — | ✓ (temporal refs) | via `sendedatum` |
| `context` (thematic) | — | ✓ (optional) | ✓ |
| `transcript` | ✓ | ✓ | — |
| `previous_block_ending` | — | ✓ | — |
| `sprecher` | — | — | ✓ |
| `behauptung` | — | — | ✓ |

`guests` is a `list[str]` in `"Name (Rolle)"` format rather than a free-text blob. This gives the LLM structured, unambiguous signal while keeping the config simple. The thematic `context` (`Episode.context`) is kept separate from the guest list so the model can distinguish who is speaking from what the show is about.
