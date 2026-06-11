# Session-Setup-Wizard + Conversation Generalization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat `/new` form with a guided, branched setup wizard, and generalize the LLM pipeline from "TV-show" to any conversation (debate / interview / private) via a neutral prompt set plus a `conversation_type` signal — while removing the now-meaningless user-supplied "Sendedatum" from the extraction path.

**Architecture:** Backend gains one `conversation_type` column (idempotent migration) threaded into the two extraction inputs; the show-specific date input is removed from claim extraction (the fact-checker keeps its own real `now()`); the two show-framed prompts are neutralized. The frontend extracts all bug-prone wizard logic (per-type participant formatting, defaults, title derivation, step reducer) into a pure, unit-tested module, with a thin React wizard shell on `/new`.

**Tech Stack:** Python 3.12 / FastAPI / aiosqlite / PydanticAI (backend, pytest + `TestModel`/`FunctionModel`), React 18 + Vite (frontend, new vitest for pure logic), `bun`, `uv`, `ruff`.

**Conventions used throughout:**
- Run backend tests: `uv run pytest backend/tests -m "not integration" -q`
- Lint: `uv run ruff check backend/`
- Frontend logic tests: `cd frontend && bun run test`
- Frontend build: `cd frontend && bun run build`
- Commits: short one-line message, **no co-author trailer** (project rule).
- `conversation_type` canonical values: `"debate" | "interview" | "private"`, default `"debate"`.
- German type labels: `debate → "Öffentliche Debatte"`, `interview → "Interview"`, `private → "Privates Gespräch"`.

---

## File Structure

**Backend (modify):**
- `backend/database.py` — `sessions` schema + migration + `_row_to_session` + `add_session` gain `conversation_type`.
- `backend/models.py` — `CreateSessionRequest` + `SessionResponse` gain `conversation_type`.
- `backend/routers/sessions.py` — persist `conversation_type`.
- `config.py` — `Episode.conversation_type` + `from_session_row` + `episode_to_session_dict`.
- `backend/services/claim_extraction.py` — drop `date` from `ClaimExtractionInput` + method signatures; add `conversation_type` to `ClaimExtractionInput` + `SpeakerLabelsInput`; neutralize field descriptions.
- `backend/routers/audio.py` — drop `ep_date`; thread `conversation_type`.
- `backend/routers/claims.py` — text-block: stop passing `date` into extraction.
- `prompts/claim_extraction.md`, `prompts/speaker_labels.md` — neutralize show framing.

**Frontend (create/modify):**
- `frontend/src/wizard/wizardLogic.js` (create) — pure logic.
- `frontend/src/wizard/wizardLogic.test.js` (create) — vitest unit tests.
- `frontend/package.json` (modify) — add `vitest` + `test` script.
- `frontend/src/pages/NewSessionPage.jsx` (rewrite) — wizard shell.
- `frontend/src/App.css` (append) — wizard styles.

**Tests (create/modify):**
- `backend/tests/test_database_sessions.py`, `test_api_sessions.py`, `test_config_sessions.py`, `test_claim_extraction.py`, `test_audio_pipeline.py` (modify).
- `backend/tests/test_prompts_generalization.py` (create).

---

## Task 1: DB — `conversation_type` column + migration

**Files:**
- Modify: `backend/database.py` (CREATE TABLE sessions ~82, migrations ~120, `_row_to_session` ~258, `add_session` ~274)
- Test: `backend/tests/test_database_sessions.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_database_sessions.py`:

```python
async def test_add_session_persists_conversation_type():
    from backend.database import Database
    db = Database(":memory:")
    await db.connect()
    await db.add_session({"session_id": "ct1", "title": "T", "conversation_type": "interview",
                          "created_at": "2026-06-11"})
    s = await db.get_session("ct1")
    assert s["conversation_type"] == "interview"
    await db.close()


async def test_add_session_defaults_conversation_type_to_debate():
    from backend.database import Database
    db = Database(":memory:")
    await db.connect()
    await db.add_session({"session_id": "ct2", "title": "T", "created_at": "2026-06-11"})
    s = await db.get_session("ct2")
    assert s["conversation_type"] == "debate"
    await db.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_database_sessions.py -k conversation_type -q`
Expected: FAIL (`KeyError: 'conversation_type'`).

- [ ] **Step 3: Implement the schema, migration, mapping, and insert**

In `backend/database.py`, add the column to the `CREATE TABLE IF NOT EXISTS sessions` block (after the `type` line, before `status`):

```python
                type             TEXT NOT NULL DEFAULT 'show',
                conversation_type TEXT NOT NULL DEFAULT 'debate',
                status           TEXT NOT NULL DEFAULT 'active',
```

Add a migration block (next to the existing codes-quota migration loop):

```python
        # Migration: add conversation_type to existing sessions tables
        for migration in [
            "ALTER TABLE sessions ADD COLUMN conversation_type TEXT NOT NULL DEFAULT 'debate'",
        ]:
            try:
                await self.db.execute(migration)
                await self.db.commit()
            except Exception:
                pass  # Column already exists
```

In `_row_to_session`, add the key (after `"type": row["type"],`):

```python
            "type": row["type"],
            "conversation_type": row["conversation_type"],
```

In `add_session`, add the column to the INSERT column list, the placeholders, and the value tuple:

```python
            """INSERT INTO sessions
               (session_id, title, date, guests, context, reference_links,
                type, conversation_type, status, visibility, owner_code, created_at, ended_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session["session_id"],
                session.get("title", ""),
                session.get("date", ""),
                json.dumps(session.get("guests", []), ensure_ascii=False),
                session.get("context", ""),
                json.dumps(session.get("reference_links", []), ensure_ascii=False),
                session.get("type", "show"),
                session.get("conversation_type", "debate"),
                session.get("status", "active"),
                session.get("visibility", "private"),
                session.get("owner_code"),
                session.get("created_at", datetime.now().isoformat()),
                session.get("ended_at"),
            ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_database_sessions.py -q`
Expected: PASS (all session DB tests).

- [ ] **Step 5: Commit**

```bash
git add backend/database.py backend/tests/test_database_sessions.py
git commit -m "Phase 2: add conversation_type column to sessions"
```

---

## Task 2: API models + sessions router

**Files:**
- Modify: `backend/models.py:79-86` (`CreateSessionRequest`), `backend/models.py:135-147` (`SessionResponse`)
- Modify: `backend/routers/sessions.py:20-33` (row dict)
- Test: `backend/tests/test_api_sessions.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_api_sessions.py`:

```python
async def test_create_session_accepts_conversation_type(client):
    resp = await client.post("/api/sessions", json={"title": "I", "conversation_type": "private"})
    assert resp.status_code == 201
    assert resp.json()["conversation_type"] == "private"


async def test_create_session_defaults_conversation_type(client):
    resp = await client.post("/api/sessions", json={"title": "T"})
    assert resp.status_code == 201
    assert resp.json()["conversation_type"] == "debate"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_api_sessions.py -k conversation_type -q`
Expected: FAIL (response has no `conversation_type` / field ignored).

- [ ] **Step 3: Implement model + router changes**

In `backend/models.py`, `CreateSessionRequest` — add after `type: str = "show"`:

```python
    type: str = "show"
    conversation_type: str = "debate"
```

In `backend/models.py`, `SessionResponse` — add after `type: str = "show"`:

```python
    type: str = "show"
    conversation_type: str = "debate"
```

In `backend/routers/sessions.py`, add to the `row` dict (after `"type": request.type,`):

```python
        "type": request.type,
        "conversation_type": request.conversation_type,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_api_sessions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/models.py backend/routers/sessions.py backend/tests/test_api_sessions.py
git commit -m "Phase 2: accept and return conversation_type on sessions API"
```

---

## Task 3: `Episode` view-model + mappings

**Files:**
- Modify: `config.py:43-87` (`Episode` dataclass + `from_session_row`), `config.py:239-252` (`episode_to_session_dict`)
- Test: `backend/tests/test_config_sessions.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_config_sessions.py`:

```python
def test_from_session_row_reads_conversation_type():
    from config import Episode
    ep = Episode.from_session_row({"session_id": "s", "conversation_type": "interview"})
    assert ep.conversation_type == "interview"


def test_from_session_row_defaults_conversation_type():
    from config import Episode
    ep = Episode.from_session_row({"session_id": "s"})
    assert ep.conversation_type == "debate"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_config_sessions.py -k conversation_type -q`
Expected: FAIL (`AttributeError: 'Episode' object has no attribute 'conversation_type'`).

- [ ] **Step 3: Implement Episode field + mappings**

In `config.py`, add the field to the `Episode` dataclass (after `type: str = "show"`):

```python
    type: str = "show"
    conversation_type: str = "debate"
    publish: bool = False
```

In `Episode.from_session_row`, add (after `type=row.get("type", "show"),`):

```python
            type=row.get("type", "show"),
            conversation_type=row.get("conversation_type", "debate"),
```

In `episode_to_session_dict`, add (after `"type": ep.type,`):

```python
        "type": ep.type,
        "conversation_type": ep.conversation_type,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_config_sessions.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config.py backend/tests/test_config_sessions.py
git commit -m "Phase 2: thread conversation_type through Episode view-model"
```

---

## Task 4: Claim-extraction — drop `date`, add `conversation_type`, neutralize descriptions

**Files:**
- Modify: `backend/services/claim_extraction.py:50-62` (input models), `:116-156` (methods)
- Test: `backend/tests/test_claim_extraction.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_claim_extraction.py` (it already imports `FunctionModel`, `AgentInfo`, `ModelMessage`, `ModelResponse`, and defines `_empty_claims_model()` — reuse them):

```python
    def test_claim_extraction_input_drops_date_adds_conversation_type(self):
        """The date field is gone; conversation_type is present."""
        from backend.services.claim_extraction import ClaimExtractionInput, SpeakerLabelsInput
        assert "date" not in ClaimExtractionInput.model_fields
        assert "conversation_type" in ClaimExtractionInput.model_fields
        assert "conversation_type" in SpeakerLabelsInput.model_fields

    async def test_extract_passes_conversation_type(self, mock_claim_extractor):
        """conversation_type reaches the model as part of the user message."""
        captured = {}

        async def capture(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            for part in messages[-1].parts:
                content = getattr(part, "content", None)
                if isinstance(content, str):
                    captured["user_message"] = content
            return await _empty_claims_model().request(messages, info.model_settings, info.model_request_parameters)

        with mock_claim_extractor.claim_extractor.override(model=FunctionModel(capture)):
            await mock_claim_extractor.extract_claims_async(
                "Test transcript", ["Speaker A"], conversation_type="private"
            )

        assert "private" in captured["user_message"]
```

> Place both methods inside the existing `TestClaimExtractorAsync`/equivalent class (indentation = 4 spaces under the class). If `_empty_claims_model` is module-level, the call above works as written; if it is a class method, call `self._empty_claims_model()`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_claim_extraction.py -k "conversation_type or drops_date" -q`
Expected: FAIL (`date` still present / `conversation_type` unexpected kwarg).

- [ ] **Step 3: Update input models + field descriptions**

In `backend/services/claim_extraction.py`, replace `SpeakerLabelsInput` and `ClaimExtractionInput`:

```python
class SpeakerLabelsInput(BaseModel):
    """Input for speaker label resolution."""
    conversation_type: str = Field(default="", description="Art des Gesprächs: 'debate' (öffentliche Debatte/Talkshow), 'interview' oder 'private' (privates Gespräch).")
    guests: list[str] = Field(description="Teilnehmer des Gesprächs, z. B. ['Caren Miosga (Moderatorin)', 'Heidi Reichinnek (Linke)'] — bei privaten Gesprächen ggf. nur Vornamen.")
    transcript: str = Field(description="Transkript mit generischen Sprecherbezeichnungen")


class ClaimExtractionInput(BaseModel):
    """Input for claim extraction from a transcript."""
    conversation_type: str = Field(default="", description="Art des Gesprächs: 'debate' (öffentliche Debatte/Talkshow), 'interview' oder 'private' (privates Gespräch).")
    guests: list[str] = Field(description="Teilnehmer des Gesprächs")
    context: str = Field(default="", description="Thematischer Hintergrund des Gesprächs")
    transcript: str = Field(description="Transkript zur Analyse")
    previous_block_ending: str | None = Field(default=None, description="Letzte Zeilen des vorherigen Transkriptblocks zur Gewährleistung der Kontinuität")
```

- [ ] **Step 4: Update method signatures + bodies**

Replace the four methods (`_resolve_speaker_labels_async`, `resolve_labels_async`, `extract_claims_async`, `extract_async`, `extract`) so `date` is gone and `conversation_type` is threaded:

```python
    async def _resolve_speaker_labels_async(self, transcript: str, guests: list[str], conversation_type: str = "") -> str:
        """Step 1: Identify speaker label->name mappings and apply them to the transcript."""
        user_message = SpeakerLabelsInput(
            conversation_type=conversation_type, guests=guests, transcript=transcript
        ).model_dump_json(indent=2)
        result = await self.speaker_resolver.run(user_message)
        for m in sorted(result.output.mappings, key=lambda x: len(x.label), reverse=True):
            transcript = transcript.replace(m.label, m.name)
        return transcript

    async def resolve_labels_async(self, transcript: str, guests: list[str], conversation_type: str = "") -> str:
        """Resolve generic speaker labels to real names. Returns transcript unchanged if no resolver."""
        if self.speaker_resolver:
            return await self._resolve_speaker_labels_async(transcript, guests, conversation_type)
        return transcript

    async def extract_claims_async(self, resolved_transcript: str, guests: list[str], context: str = "", previous_context: str | None = None, conversation_type: str = "") -> List[ExtractedClaim]:
        """Extract claims from an already-resolved transcript. Skips speaker label resolution."""
        logger.info(f"Extracting claims from resolved transcript ({len(resolved_transcript)} chars)")
        user_message = ClaimExtractionInput(
            conversation_type=conversation_type, guests=guests, context=context,
            transcript=resolved_transcript, previous_block_ending=previous_context,
        ).model_dump_json(indent=2)
        result = await self.claim_extractor.run(user_message)
        logger.info(f"Extraction complete: {len(result.output.claims)} claims found")
        return result.output.claims

    async def extract_async(self, transcript: str, guests: list[str], context: str = "", previous_context: str | None = None, conversation_type: str = "") -> List[ExtractedClaim]:
        """Extract claims, resolving speaker labels first (text-block pipeline entry point)."""
        logger.info(f"Extracting claims from transcript ({len(transcript)} chars)")
        if self.speaker_resolver:
            transcript = await self._resolve_speaker_labels_async(transcript, guests, conversation_type)
            logger.info(f"Speaker labels resolved ({len(transcript)} chars)")
        return await self.extract_claims_async(transcript, guests, context=context, previous_context=previous_context, conversation_type=conversation_type)

    def extract(self, transcript: str, guests: list[str], context: str = "", previous_context: str | None = None, conversation_type: str = "") -> List[ExtractedClaim]:
        """Sync wrapper for extract_async()."""
        return asyncio.run(self.extract_async(transcript, guests, context=context, previous_context=previous_context, conversation_type=conversation_type))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_claim_extraction.py -q`
Expected: PASS (new + existing — existing tests never passed `date=`, so they are unaffected).

- [ ] **Step 6: Commit**

```bash
git add backend/services/claim_extraction.py backend/tests/test_claim_extraction.py
git commit -m "Phase 2: drop Sendedatum, add conversation_type to claim extraction"
```

---

## Task 5: Wire `conversation_type` through the pipelines; remove date from callers

**Files:**
- Modify: `backend/routers/audio.py:108-165`
- Modify: `backend/routers/claims.py:89`
- Test: `backend/tests/test_audio_pipeline.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_audio_pipeline.py` (mirrors the existing `test_previous_block_ending_passed_with_resolved_names`):

```python
async def test_conversation_type_passed_to_extractor(mock_audio_file):
    """The session's conversation_type reaches resolve + extract."""
    mock_transcription = MagicMock()
    mock_transcription.transcribe = MagicMock(return_value="Sprecher A: Test.")

    mock_extractor = MagicMock()
    mock_extractor.resolve_labels_async = AsyncMock(return_value="Anna: Test.")
    mock_extractor.extract_claims_async = AsyncMock(return_value=[])

    state.last_transcript_tail = None
    state.pipeline_events["ct-block"] = {"status": "processing"}

    await state.get_db().add_session({
        "session_id": "ct-sess", "title": "t", "guests": ["Anna"],
        "context": "ctx", "conversation_type": "private",
    })

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_transcription), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_extractor):
        await process_audio_pipeline_async("ct-block", mock_audio_file, "ct-sess")

    assert mock_extractor.resolve_labels_async.call_args.kwargs.get("conversation_type") == "private"
    assert mock_extractor.extract_claims_async.call_args.kwargs.get("conversation_type") == "private"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_audio_pipeline.py -k conversation_type -q`
Expected: FAIL (`conversation_type` not in call kwargs).

- [ ] **Step 3: Update `audio.py`**

In `backend/routers/audio.py`, replace the `ep_*` extraction block (~110-113):

```python
    ep = Episode.from_session_row(session) if session else None
    ep_guests = ep.guests if ep else []
    ep_context = ep.context if ep else ""
    ep_conversation_type = ep.conversation_type if ep else "debate"
```

(remove the `ep_date = ep.date if ep else ""` line.)

Update the resolve call (~153):

```python
        resolved_transcript = await claim_extractor.resolve_labels_async(transcript, ep_guests, conversation_type=ep_conversation_type)
```

Update the extract call (~162-165):

```python
        claims = await claim_extractor.extract_claims_async(
            resolved_transcript, ep_guests,
            context=ep_context, previous_context=previous_context,
            conversation_type=ep_conversation_type,
        )
```

- [ ] **Step 4: Update `claims.py` text-block caller**

In `backend/routers/claims.py:89`, drop the `date=` argument (the article `publication_date` is no longer fed to extraction; the fact-checker uses its own real date):

```python
        claims = await claim_extractor.extract_async(text, guests=[], context=headline)
```

(Leave the `publication_date` parameter on `process_text_pipeline_async` in place — the n8n webhook still sends it — it is simply no longer forwarded to extraction.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_audio_pipeline.py backend/tests/test_api_claims.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/routers/audio.py backend/routers/claims.py backend/tests/test_audio_pipeline.py
git commit -m "Phase 2: thread conversation_type through pipelines, drop date from extraction callers"
```

---

## Task 6: Neutralize the show-framed prompts (with guard test)

**Files:**
- Modify: `prompts/claim_extraction.md:1-3`, `prompts/speaker_labels.md`
- Test: `backend/tests/test_prompts_generalization.py` (create)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_prompts_generalization.py`:

```python
"""Guards that the extraction/speaker prompts are conversation-neutral (not TV-show-only)."""
from backend.utils import load_prompt


def test_claim_extraction_prompt_is_conversation_neutral():
    p = load_prompt("claim_extraction.md")
    assert "Talkshow" not in p


def test_speaker_labels_prompt_treats_party_as_optional():
    p = load_prompt("speaker_labels.md")
    assert "falls vorhanden" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_prompts_generalization.py -q`
Expected: FAIL (`"Talkshow"` still present; `"falls vorhanden"` absent).

- [ ] **Step 3: Edit `prompts/claim_extraction.md`**

Replace the `<Rolle>` line:

```
<Rolle>
Professionelle:r Inhaltsanalyst:in für deutschsprachige Gesprächs- und Transkriptanalyse.
</Rolle>
```

- [ ] **Step 4: Edit `prompts/speaker_labels.md`**

Replace the second bullet under `<Regeln>` (the party-framed `Den Informationen ueber die Gaeste ...` line) with:

```
2. Den verfügbaren Informationen über die Teilnehmenden (z. B. Rolle/Funktion, Organisation oder Partei – falls vorhanden; bei privaten Gesprächen ggf. nur Vorname).
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest backend/tests/test_prompts_generalization.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add prompts/claim_extraction.md prompts/speaker_labels.md backend/tests/test_prompts_generalization.py
git commit -m "Phase 2: neutralize show-specific framing in extraction prompts"
```

---

## Task 7: Frontend — pure wizard logic + vitest

**Files:**
- Create: `frontend/src/wizard/wizardLogic.js`
- Create: `frontend/src/wizard/wizardLogic.test.js`
- Modify: `frontend/package.json`

- [ ] **Step 1: Add vitest and a test script**

Run: `cd frontend && bun add -d vitest`
Then in `frontend/package.json`, add to `"scripts"`:

```json
    "preview": "vite preview",
    "test": "vitest run"
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/wizard/wizardLogic.test.js`:

```js
import { describe, it, expect } from 'vitest'
import {
  TYPE_LABELS, STEPS, initialWizardState, wizardReducer,
  formatParticipant, buildGuests, defaultContext, deriveTitle, buildSessionPayload,
} from './wizardLogic'

describe('formatParticipant', () => {
  it('debate: name + party + role', () => {
    expect(formatParticipant('debate', { name: 'Heidi Reichinnek', party: 'Linke', role: 'Fraktionsvorsitzende' }))
      .toBe('Heidi Reichinnek (Linke, Fraktionsvorsitzende)')
  })
  it('private: omits party, keeps optional role', () => {
    expect(formatParticipant('private', { name: 'Onkel Klaus', party: 'CDU', role: '' })).toBe('Onkel Klaus')
    expect(formatParticipant('private', { name: 'Klaus', party: '', role: 'Nachbar' })).toBe('Klaus (Nachbar)')
  })
  it('empty name => empty string', () => {
    expect(formatParticipant('debate', { name: '   ', party: 'X', role: 'Y' })).toBe('')
  })
})

describe('buildGuests', () => {
  it('filters out empty people', () => {
    const people = [{ name: 'A', party: '', role: '' }, { name: '', party: '', role: '' }]
    expect(buildGuests('debate', people)).toEqual(['A'])
  })
})

describe('defaultContext', () => {
  it('maps each type to its German label', () => {
    expect(defaultContext('debate')).toBe(TYPE_LABELS.debate)
    expect(defaultContext('interview')).toBe('Interview')
    expect(defaultContext('private')).toBe('Privates Gespräch')
  })
})

describe('deriveTitle', () => {
  it('uses first named participant', () => {
    expect(deriveTitle('interview', [{ name: 'Robert Habeck' }])).toBe('Interview: Robert Habeck')
  })
  it('falls back to type label when nobody is named', () => {
    expect(deriveTitle('private', [{ name: '' }])).toBe('Privates Gespräch')
  })
})

describe('buildSessionPayload', () => {
  it('skipped topic => type-default context; date empty; no reference links', () => {
    const s = { ...initialWizardState(), conversationType: 'private',
                people: [{ name: 'Klaus', party: '', role: '' }], topic: '', title: '' }
    expect(buildSessionPayload(s)).toEqual({
      title: 'Privates Gespräch: Klaus',
      conversation_type: 'private',
      guests: ['Klaus'],
      context: 'Privates Gespräch',
      date: '',
      reference_links: [],
      type: 'show',
    })
  })
  it('explicit topic and edited title win', () => {
    const s = { ...initialWizardState(), conversationType: 'debate',
                people: [{ name: 'A', party: 'SPD', role: '' }], topic: 'Rente', title: 'Mein Titel' }
    const p = buildSessionPayload(s)
    expect(p.context).toBe('Rente')
    expect(p.title).toBe('Mein Titel')
    expect(p.guests).toEqual(['A (SPD)'])
  })
})

describe('wizardReducer', () => {
  it('SET_TYPE interview seeds two person slots', () => {
    const s = wizardReducer(initialWizardState(), { type: 'SET_TYPE', value: 'interview' })
    expect(s.conversationType).toBe('interview')
    expect(s.people).toHaveLength(2)
  })
  it('ADD_PERSON / REMOVE_PERSON / UPDATE_PERSON', () => {
    let s = wizardReducer(initialWizardState(), { type: 'SET_TYPE', value: 'debate' })
    s = wizardReducer(s, { type: 'ADD_PERSON' })
    expect(s.people).toHaveLength(2)
    s = wizardReducer(s, { type: 'UPDATE_PERSON', index: 0, field: 'name', value: 'Z' })
    expect(s.people[0].name).toBe('Z')
    s = wizardReducer(s, { type: 'REMOVE_PERSON', index: 1 })
    expect(s.people).toHaveLength(1)
  })
  it('NEXT/BACK clamp within STEPS bounds', () => {
    let s = initialWizardState()
    for (let i = 0; i < 10; i++) s = wizardReducer(s, { type: 'NEXT' })
    expect(s.step).toBe(STEPS.length - 1)
    for (let i = 0; i < 10; i++) s = wizardReducer(s, { type: 'BACK' })
    expect(s.step).toBe(0)
  })
})
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && bun run test`
Expected: FAIL (cannot resolve `./wizardLogic`).

- [ ] **Step 4: Implement `wizardLogic.js`**

Create `frontend/src/wizard/wizardLogic.js`:

```js
// Pure, framework-free wizard logic — unit-tested in wizardLogic.test.js.

export const CONVERSATION_TYPES = ['debate', 'interview', 'private']

export const TYPE_LABELS = {
  debate: 'Öffentliche Debatte',
  interview: 'Interview',
  private: 'Privates Gespräch',
}

export const STEPS = ['type', 'people', 'topic', 'review']

const emptyPerson = () => ({ name: '', party: '', role: '' })

export function initialWizardState() {
  return {
    step: 0,
    conversationType: null,
    people: [emptyPerson()],
    topic: '',
    title: '',
    titleEdited: false,
  }
}

export function formatParticipant(type, person) {
  const name = (person.name || '').trim()
  if (!name) return ''
  const parts = []
  if (type !== 'private' && (person.party || '').trim()) parts.push(person.party.trim())
  if ((person.role || '').trim()) parts.push(person.role.trim())
  return parts.length ? `${name} (${parts.join(', ')})` : name
}

export function buildGuests(type, people) {
  return people.map((p) => formatParticipant(type, p)).filter(Boolean)
}

export function defaultContext(type) {
  return TYPE_LABELS[type] || ''
}

export function deriveTitle(type, people) {
  const label = TYPE_LABELS[type] || 'Gespräch'
  const firstNamed = people.map((p) => (p.name || '').trim()).find(Boolean)
  return firstNamed ? `${label}: ${firstNamed}` : label
}

export function buildSessionPayload(state) {
  const type = state.conversationType
  return {
    title: (state.title && state.title.trim()) || deriveTitle(type, state.people),
    conversation_type: type,
    guests: buildGuests(type, state.people),
    context: state.topic.trim() || defaultContext(type),
    date: '',
    reference_links: [],
    type: 'show',
  }
}

export function wizardReducer(state, action) {
  switch (action.type) {
    case 'SET_TYPE': {
      const people = action.value === 'interview'
        ? [emptyPerson(), emptyPerson()]
        : [emptyPerson()]
      return { ...state, conversationType: action.value, people }
    }
    case 'ADD_PERSON':
      return { ...state, people: [...state.people, emptyPerson()] }
    case 'REMOVE_PERSON':
      return { ...state, people: state.people.filter((_, i) => i !== action.index) }
    case 'UPDATE_PERSON':
      return {
        ...state,
        people: state.people.map((p, i) =>
          i === action.index ? { ...p, [action.field]: action.value } : p),
      }
    case 'SET_TOPIC':
      return { ...state, topic: action.value }
    case 'SET_TITLE':
      return { ...state, title: action.value, titleEdited: true }
    case 'NEXT':
      return { ...state, step: Math.min(state.step + 1, STEPS.length - 1) }
    case 'BACK':
      return { ...state, step: Math.max(state.step - 1, 0) }
    default:
      return state
  }
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && bun run test`
Expected: PASS (all wizardLogic specs).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/wizard/wizardLogic.js frontend/src/wizard/wizardLogic.test.js frontend/package.json frontend/bun.lockb
git commit -m "Phase 2: pure wizard logic module + vitest"
```

---

## Task 8: Frontend — wizard UI on `/new`

**Files:**
- Rewrite: `frontend/src/pages/NewSessionPage.jsx`
- Append: `frontend/src/App.css`

- [ ] **Step 1: Rewrite `NewSessionPage.jsx` as the wizard shell**

Replace the entire file with:

```jsx
import { useReducer, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createSession, getAccessCode, setAccessCode } from '../services/api'
import {
  TYPE_LABELS, STEPS, initialWizardState, wizardReducer, buildSessionPayload,
} from '../wizard/wizardLogic'

const TYPE_TILES = [
  { value: 'debate', icon: '🏛️', label: 'Öffentliche Debatte / Talkshow' },
  { value: 'interview', icon: '🎙️', label: 'Interview' },
  { value: 'private', icon: '💬', label: 'Privates Gespräch' },
]

function PersonFields({ person, index, type, dispatch, removable }) {
  const upd = (field) => (e) =>
    dispatch({ type: 'UPDATE_PERSON', index, field, value: e.target.value })
  return (
    <div className="wizard-person">
      <input className="wizard-input" value={person.name} onChange={upd('name')}
             placeholder="Name" />
      {type !== 'private' && (
        <input className="wizard-input" value={person.party} onChange={upd('party')}
               placeholder="Partei / Organisation" />
      )}
      <input className="wizard-input" value={person.role} onChange={upd('role')}
             placeholder={type === 'private' ? 'Rolle (optional, z. B. Nachbar)' : 'Rolle / Funktion'} />
      {removable && (
        <button type="button" className="wizard-remove"
                onClick={() => dispatch({ type: 'REMOVE_PERSON', index })}>Entfernen</button>
      )}
    </div>
  )
}

export function NewSessionPage() {
  const navigate = useNavigate()
  const [state, dispatch] = useReducer(wizardReducer, undefined, initialWizardState)
  const [accessCode, setAccessCodeInput] = useState(getAccessCode())
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const needsCode = !getAccessCode()
  const stepName = STEPS[state.step]

  const canAdvance = () => {
    if (stepName === 'type') return !!state.conversationType
    return true
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    setError(null)
    if (accessCode) setAccessCode(accessCode.trim())
    try {
      const result = await createSession(buildSessionPayload(state))
      if (!result?.session_id) throw new Error('Keine Session-ID erhalten')
      navigate('/' + result.session_id)
    } catch (err) {
      const msg = err.message || 'Fehler beim Erstellen der Session'
      if (/401|403|Zugangscode/i.test(msg)) setAccessCode('')
      setError(msg)
      setSubmitting(false)
    }
  }

  return (
    <div className="about-page">
      <div className="about-content wizard">
        <div className="wizard-progress">
          {STEPS.map((s, i) => (
            <span key={s} className={`wizard-dot ${i === state.step ? 'active' : ''} ${i < state.step ? 'done' : ''}`} />
          ))}
        </div>

        {stepName === 'type' && (
          <section className="wizard-step">
            <h1>Was für ein Gespräch?</h1>
            <div className="wizard-tiles">
              {TYPE_TILES.map((t) => (
                <button key={t.value} type="button"
                        className={`wizard-tile ${state.conversationType === t.value ? 'selected' : ''}`}
                        onClick={() => dispatch({ type: 'SET_TYPE', value: t.value })}>
                  <span className="wizard-tile-icon">{t.icon}</span>
                  <span>{t.label}</span>
                </button>
              ))}
            </div>
          </section>
        )}

        {stepName === 'people' && (
          <section className="wizard-step">
            <h1>Wer spricht?</h1>
            {state.conversationType === 'interview' && (
              <p className="wizard-hint">Erste Person = interviewt, zweite = interviewende Person/Medium (optional).</p>
            )}
            {state.conversationType === 'private' && (
              <p className="wizard-hint">Nur Vornamen/Rollen genügen — keine Partei nötig. Du kannst diesen Schritt auch leer lassen.</p>
            )}
            {state.people.map((p, i) => (
              <PersonFields key={i} person={p} index={i} type={state.conversationType}
                            dispatch={dispatch}
                            removable={state.conversationType !== 'interview' && state.people.length > 1} />
            ))}
            {state.conversationType !== 'interview' && (
              <button type="button" className="wizard-add"
                      onClick={() => dispatch({ type: 'ADD_PERSON' })}>+ weitere Person</button>
            )}
          </section>
        )}

        {stepName === 'topic' && (
          <section className="wizard-step">
            <h1>Worum geht es? <span className="wizard-optional">(optional)</span></h1>
            <textarea className="wizard-input" rows={4} value={state.topic}
                      onChange={(e) => dispatch({ type: 'SET_TOPIC', value: e.target.value })}
                      placeholder="Thema / Hintergrund — kann leer bleiben" />
          </section>
        )}

        {stepName === 'review' && (
          <section className="wizard-step">
            <h1>Übersicht</h1>
            <dl className="wizard-summary">
              <dt>Art</dt><dd>{TYPE_LABELS[state.conversationType]}</dd>
              <dt>Personen</dt><dd>{buildSessionPayload(state).guests.join(', ') || '—'}</dd>
              <dt>Thema</dt><dd>{buildSessionPayload(state).context}</dd>
            </dl>
            <div className="form-field">
              <label htmlFor="wizard-title">Titel</label>
              <input id="wizard-title" className="wizard-input"
                     value={state.title || buildSessionPayload(state).title}
                     onChange={(e) => dispatch({ type: 'SET_TITLE', value: e.target.value })} />
            </div>
            {needsCode && (
              <div className="form-field">
                <label htmlFor="wizard-code">Zugangscode</label>
                <input id="wizard-code" type="password" className="wizard-input" autoComplete="off"
                       value={accessCode} onChange={(e) => setAccessCodeInput(e.target.value)}
                       placeholder="Dein persönlicher Zugangscode" />
              </div>
            )}
            {error && <p className="form-error">{error}</p>}
          </section>
        )}

        <div className="wizard-nav">
          {state.step > 0 && (
            <button type="button" className="action-button"
                    onClick={() => dispatch({ type: 'BACK' })} disabled={submitting}>Zurück</button>
          )}
          {stepName !== 'review' ? (
            <button type="button" className="action-button primary"
                    onClick={() => dispatch({ type: 'NEXT' })} disabled={!canAdvance()}>Weiter</button>
          ) : (
            <button type="button" className="action-button primary"
                    onClick={handleSubmit} disabled={submitting}>
              {submitting ? 'Wird erstellt...' : 'Session erstellen'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Append wizard styles to `App.css`**

Append:

```css
/* ---- Session-Setup-Wizard ---- */
.wizard { max-width: 640px; }
.wizard-progress { display: flex; gap: 8px; justify-content: center; margin-bottom: 28px; }
.wizard-dot { width: 10px; height: 10px; border-radius: 50%; background: #d0d4dd; transition: background .2s; }
.wizard-dot.active { background: #2563eb; }
.wizard-dot.done { background: #93b4f5; }
.wizard-step { animation: wizardFade .25s ease; }
@keyframes wizardFade { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.wizard-tiles { display: grid; gap: 12px; margin-top: 20px; }
.wizard-tile { display: flex; align-items: center; gap: 14px; padding: 18px 20px; border: 2px solid #e2e6ee;
  border-radius: 14px; background: #fff; color: #1f2533; font-size: 1.05rem; cursor: pointer; text-align: left; transition: border-color .15s, box-shadow .15s; }
.wizard-tile:hover { border-color: #b9c6e8; }
.wizard-tile.selected { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,.15); }
.wizard-tile-icon { font-size: 1.6rem; }
.wizard-person { display: grid; gap: 8px; padding: 14px; border: 1px solid #e2e6ee; border-radius: 12px; margin-bottom: 12px; background: #fff; }
.wizard-input { width: 100%; padding: 10px 12px; border: 1px solid #cfd5e1; border-radius: 8px;
  background: #fff; color: #1f2533; font-size: 1rem; }
.wizard-input::placeholder { color: #8a93a6; }
.wizard-add, .wizard-remove { align-self: start; background: none; border: none; color: #2563eb; cursor: pointer; padding: 4px 0; font-size: .95rem; }
.wizard-remove { color: #b04242; }
.wizard-hint, .wizard-optional { color: #6b7280; font-size: .9rem; }
.wizard-summary { display: grid; grid-template-columns: auto 1fr; gap: 6px 16px; margin: 16px 0; }
.wizard-summary dt { color: #6b7280; }
.wizard-summary dd { margin: 0; color: #1f2533; }
.wizard-nav { display: flex; justify-content: space-between; gap: 12px; margin-top: 28px; }
.wizard-nav .action-button.primary { margin-left: auto; }
```

- [ ] **Step 3: Build to verify it compiles**

Run: `cd frontend && bun run build`
Expected: build succeeds, no errors. (Leave `frontend/dist/` untracked — never commit it.)

- [ ] **Step 4: Manual click-test (dev server)**

Run backend + frontend (`./start_dev.sh <any-existing-episode-key>` or `cd frontend && bun run dev`), open `/new`, and verify for each type:
- debate: add 2 people with party+role → review shows `Name (Partei, Rolle)`.
- interview: exactly two slots; second optional.
- private: party field hidden; can proceed with empty people; context defaults to "Privates Gespräch".
- Skipping the topic step yields the type-default context in the review summary.
- "Session erstellen" navigates to `/{session_id}`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/NewSessionPage.jsx frontend/src/App.css
git commit -m "Phase 2: guided session setup wizard on /new"
```

---

## Task 9: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Backend unit tests**

Run: `uv run pytest backend/tests -m "not integration" -q`
Expected: all PASS (≥ 209 prior + new tests).

- [ ] **Step 2: Lint**

Run: `uv run ruff check backend/`
Expected: clean (no errors).

- [ ] **Step 3: Frontend logic tests + build**

Run: `cd frontend && bun run test && bun run build`
Expected: vitest PASS, build succeeds.

- [ ] **Step 4: Confirm no `dist/` is staged**

Run: `git status --porcelain frontend/dist`
Expected: empty output (dist stays untracked).

- [ ] **Step 5: Final commit (only if verification produced fixes)**

```bash
git add -A
git commit -m "Phase 2: wizard + conversation generalization verified"
```

---

## Self-Review Notes (carried from spec → plan)

- **Spec coverage:** data model (Task 1-3), date removal (Task 4-5), prompt/field generalization (Task 4, 6), wizard UX + per-type formatting (Task 7-8), testing (every task + Task 9). ✅
- **Discovered during planning (not in spec):** `claims.py` text-block also passed `date=publication_date`. Handled in Task 5 by dropping the argument; the `publication_date` request field/param is retained for webhook compatibility but no longer reaches extraction. **Flag for the user** — if articles must keep date-aware extraction, that caller needs a different treatment.
- **Type consistency:** `conversation_type` (snake_case) everywhere backend; `conversationType` only inside the frontend wizard state, mapped to `conversation_type` in `buildSessionPayload`. Default `"debate"` consistent across DB column, model, `Episode`, and audio fallback. Method signature `extract_claims_async(resolved_transcript, guests, context="", previous_context=None, conversation_type="")` is identical in the definition (Task 4) and the audio caller (Task 5, kwargs).
- **Out of scope (unchanged):** browser audio capture, structured `participants[]` persistence, per-type prompts, reference-links in wizard, removing the legacy `date` column.
