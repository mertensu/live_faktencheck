# Storing Transcripts — Legal Notes and Plan

**Status:** Thoughts / not decided. Written 2026-09-29.
**Not legal advice** — a reading of German law to steer the design. Have a media
lawyer confirm before transcripts are stored or accounts are opened to the public.

## Question

May we keep transcripts of the conversations we fact-check? And does the answer
change once users have self-serve accounts (see `magic-link-auth-plan.md`) and can
run the tool on anything?

## Legal picture

### 1. DSGVO

A transcript with speaker names is personal data.

- **Public talk shows:** politicians' public statements on political topics.
  Legitimate interest (Art. 6 Abs. 1 lit. f) is plausible for storing them to
  document fact-checks. If the site counts as journalistic-editorial, the media
  privilege (Art. 85 DSGVO, § 23 MStV) also applies and relaxes most obligations.
- **Requirements if we store:** a stated purpose (e.g. "source record for a
  fact-check"), a fixed retention period, and a paragraph in the
  Datenschutzerklärung.
- **Transcription itself is already processing**, even without storage: AssemblyAI
  (and the LLM providers) receive the audio/text. That needs a data processing
  agreement (AVV/DPA) and a basis for the US transfer regardless of this decision.

### 2. Copyright (UrhG)

- § 48 UrhG explicitly allows use of "Reden über Tagesfragen … im Rundfunk".
- The broadcaster's right (§ 87 UrhG) protects the broadcast signal, not a text
  transcript we produce.
- Internal storage is uncritical; quoting individual passages in a fact-check is
  covered by the right to quote (§ 51 UrhG).
- **Publishing** full transcripts of whole shows is the riskier part — avoid.

### 3. Private conversations — the hard limit

Recording non-publicly spoken words without consent is a criminal offence
(§ 201 StGB). There is no household exemption for us as the operator. The wizard no
longer asks for the conversation type, but the tool can still be pointed at a
private conversation. **For those: store nothing without everyone's consent.**

## What changes with open accounts

Today only the maintainer and people with hand-issued codes run sessions — we know
what is being transcribed. With self-serve accounts we can no longer tell a public
broadcast from a kitchen-table conversation. If we stored transcripts anyway, we
would hold recorded words of third parties who never agreed, with DSGVO duties
toward them, and in the private case a § 201 problem on our side.

**Split:**

| Session run by | Transcript |
|---|---|
| Us (public shows we operate) | May be stored, with purpose, retention period, Datenschutzerklärung |
| Users (open accounts) | Processed live, **not kept** (today's behaviour). What remains is what the user wants: the fact-checks |
| Users, optional later | Per-session toggle "Transkript speichern", **off by default**, requires confirming "öffentliche Sendung oder alle Beteiligten einverstanden"; user can delete; auto-deleted after N days. The user becomes controller, we become processor → cover in the terms of use |

## What we already keep today

"We don't store transcripts" is only mostly true. Checked 2026-09-29:

1. **`fact_checks`**: claim (usually a near-quote), speaker name, reasoning, sources
   — per session, including user sessions. Much less than a transcript and easy to
   justify, but still personal data.
2. **`pending_claims_blocks.text_preview`**: the first 200 characters of every
   transcript block on the batch path (`routers/audio.py`, `routers/claims.py` via
   `utils.truncate`). A transcript fragment, kept indefinitely.
3. **Logfire — not in use, but armed.** `services/observability.py` configures
   `send_to_logfire="if-token-present"`, so nothing leaves the server today. The
   moment a `LOGFIRE_TOKEN` is set, though:
   - `logfire.instrument_pydantic_ai()` sends full LLM prompts and responses —
     every transcript window sent to extraction, gating and checking.
   - Log lines carry transcript text directly: `services/streaming.py`
     (`passage -> name: …`, first 80 chars) and `services/gate.py` (every scored
     sentence, in full).

   That would make Logfire the most complete transcript store we have, at an
   external provider. The local container logs hold the same log lines already.

## Suggested steps

1. **Now, independent of accounts:**
   - Datenschutzerklärung: mention fact-checks (claims + speaker names), the
     processors (AssemblyAI, LLM providers, Tavily) and retention.
   - Check AVV/DPA and data region for AssemblyAI.
   - Stop logging sentence text (`gate.py`, `streaming.py`) or keep container
     log retention short.
   - Before ever setting a `LOGFIRE_TOKEN`: scrub prompt content from the
     pydantic-ai instrumentation (at least for non-maintainer sessions), set a
     short retention, and add Logfire to the processor list.
   - Drop `text_preview` or give `pending_claims_blocks` a retention period.
2. **Before opening accounts:**
   - Retention rule for `fact_checks` of user sessions (e.g. deleted N days after
     the session ends, unless made public) + deletion on request, tied to the
     account's email.
   - Terms of use: user is responsible for having the right to transcribe what they
     point the tool at.
3. **If we want stored transcripts:**
   - Only for sessions marked public / run by us.
   - Prefer storing the passage around each checked claim over the full transcript:
     enough as a source record, much easier to justify.
   - Retention period (e.g. 90 days) with automatic deletion.
   - For user sessions only via the opt-in toggle above.
