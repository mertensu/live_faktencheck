# Exclude a Speaker from Fact-Checking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a session creator mark participants as "don't fact-check" so the claim extractor skips their statements, for all conversation types, fully backward-compatible.

**Architecture:** A new `excluded_speakers: list[str]` field flows from the wizard UI → `POST /api/sessions` → sessions DB row → audio pipeline → `extract_claims_async` → `ClaimExtractionInput` → the German extraction prompt, which is instructed to skip claims from those (resolved-name) speakers. Speaker-label resolution is untouched. Empty list = unchanged behaviour.

**Tech Stack:** Python 3 / FastAPI / Pydantic / aiosqlite / PydanticAI (Gemini) backend; React + Vite + Vitest frontend; pytest backend tests.

---

## File Structure

**Backend (modify):**
- `config.py` — `Episode` dataclass + `from_session_row` + `episode_to_session_dict`: carry `excluded_speakers`.
- `backend/models.py` — `CreateSessionRequest` and `SessionResponse`: add `excluded_speakers: List[str] = []`.
- `backend/database.py` — sessions table column, migration, `_row_to_session`, `add_session`.
- `backend/routers/sessions.py` — thread field into the row dict on create.
- `backend/services/claim_extraction.py` — `ClaimExtractionInput` field + `excluded_speakers` kwarg on `extract_claims_async`/`extract_async`/`extract`.
- `backend/routers/audio.py` — pass `ep.excluded_speakers` into `extract_claims_async`.
- `prompts/claim_extraction.md` — new skip rule + `user_input` doc line.

**Frontend (modify):**
- `frontend/src/wizard/wizardLogic.js` — `emptyPerson` gains `exclude`, `buildSessionPayload` derives `excluded_speakers`, `peopleStepValid` enforces named-if-excluded.
- `frontend/src/pages/NewSessionPage.jsx` — checkbox per participant.

**Tests (modify):**
- `frontend/src/wizard/wizardLogic.test.js`
- `backend/tests/test_config_sessions.py`
- `backend/tests/test_database_sessions.py`
- `backend/tests/test_api_sessions.py`
- `backend/tests/test_claim_extraction.py`
- `backend/tests/test_audio_pipeline.py`
- `backend/tests/integration/test_e2e_pipeline.py`

> **Naming note:** The design spec calls the request model `SessionCreate`; the real model is `CreateSessionRequest`. Use the real names throughout.

---

## Task 1: Frontend wizard logic — `excluded_speakers`

**Files:**
- Modify: `frontend/src/wizard/wizardLogic.js`
- Test: `frontend/src/wizard/wizardLogic.test.js`

- [ ] **Step 1: Write the failing tests**

Add to `frontend/src/wizard/wizardLogic.test.js`. Inside the existing `describe('buildSessionPayload', ...)` block add:

```javascript
  it('emits excluded_speakers from checked, named people', () => {
    const s = {
      conversationType: 'debate', topic: '', title: '', titleEdited: false,
      people: [
        { name: 'Caren Miosga', party: '', role: 'Moderatorin', exclude: true },
        { name: 'Heidi Reichinnek', party: 'Linke', role: '', exclude: false },
      ],
    }
    expect(buildSessionPayload(s).excluded_speakers).toEqual(['Caren Miosga'])
  })

  it('omits unchecked and unnamed people from excluded_speakers', () => {
    const s = {
      conversationType: 'debate', topic: '', title: '', titleEdited: false,
      people: [
        { name: '   ', party: '', role: '', exclude: true },
        { name: 'Anna', party: '', role: '', exclude: false },
      ],
    }
    expect(buildSessionPayload(s).excluded_speakers).toEqual([])
  })
```

Add a new `describe` block for the validation rule:

```javascript
describe('peopleStepValid with exclude', () => {
  it('false when a person is exclude-checked but unnamed (debate)', () => {
    expect(peopleStepValid('debate', [
      { name: 'Anna', party: '', role: '', exclude: false },
      { name: '', party: '', role: '', exclude: true },
    ])).toBe(false)
  })
  it('false when an exclude-checked person is unnamed (private)', () => {
    expect(peopleStepValid('private', [
      { name: '', party: '', role: '', exclude: true },
    ])).toBe(false)
  })
  it('true when exclude-checked people are all named', () => {
    expect(peopleStepValid('debate', [
      { name: 'Caren Miosga', party: '', role: '', exclude: true },
    ])).toBe(true)
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && bun run test -- wizardLogic`
Expected: FAIL — `excluded_speakers` is `undefined`; the exclude-validation tests fail because `peopleStepValid` ignores `exclude`.

- [ ] **Step 3: Implement the logic changes**

In `frontend/src/wizard/wizardLogic.js`:

Change `emptyPerson`:

```javascript
const emptyPerson = () => ({ name: '', party: '', role: '', exclude: false })
```

Replace `peopleStepValid` with:

```javascript
// Gating for the "people" step. Private conversations may be left empty;
// debate/interview need at least one named participant — the name is what the
// speaker-label resolver maps generic labels ("Sprecher A") onto. Party/role are
// optional but help the resolver when names aren't spoken in the transcript.
// Any participant flagged `exclude` must be named: the extractor identifies
// excluded speakers by their resolved name.
export function peopleStepValid(type, people) {
  if (people.some((p) => p.exclude && !(p.name || '').trim())) return false
  if (type === 'private') return true
  return people.some((p) => (p.name || '').trim())
}
```

In `buildSessionPayload`, add the derived field to the returned object (after `type: 'show',`):

```javascript
export function buildSessionPayload(state) {
  const type = state.conversationType
  return {
    title: (state.title && state.title.trim()) || deriveTitle(type, state.people),
    conversation_type: type,
    guests: buildGuests(type, state.people),
    context: state.topic.trim(),
    date: '',
    type: 'show',
    excluded_speakers: state.people
      .filter((p) => p.exclude && (p.name || '').trim())
      .map((p) => p.name.trim()),
  }
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && bun run test -- wizardLogic`
Expected: PASS (all wizardLogic tests, old and new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/wizard/wizardLogic.js frontend/src/wizard/wizardLogic.test.js
git commit -m "feat(wizard): derive excluded_speakers and validate named exclusions"
```

---

## Task 2: Frontend wizard UI — exclude checkbox

**Files:**
- Modify: `frontend/src/pages/NewSessionPage.jsx`

> No unit test: `PersonFields` is presentational; the logic it drives is covered in Task 1. Verify by build.

- [ ] **Step 1: Add the checkbox to `PersonFields`**

In `frontend/src/pages/NewSessionPage.jsx`, the `PersonFields` component currently ends its inputs with the `role` input and the optional remove button. Add a checkbox before the remove button. Replace the component body's `return (...)` with:

```jsx
function PersonFields({ person, index, type, dispatch, removable }) {
  const upd = (field) => (e) =>
    dispatch({ type: 'UPDATE_PERSON', index, field, value: e.target.value })
  const toggleExclude = (e) =>
    dispatch({ type: 'UPDATE_PERSON', index, field: 'exclude', value: e.target.checked })
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
      <label className="wizard-exclude">
        <input type="checkbox" checked={!!person.exclude} onChange={toggleExclude} />
        <span>Aussagen nicht prüfen</span>
      </label>
      {removable && (
        <button type="button" className="wizard-remove"
                onClick={() => dispatch({ type: 'REMOVE_PERSON', index })}>Entfernen</button>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add minimal styling**

Append to `frontend/src/App.css` (the project's stylesheet — confirm `.wizard-person` is defined there with `grep -n "wizard-person" frontend/src/App.css`; if it lives in another stylesheet, append there instead):

```css
.wizard-exclude {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.9rem;
  color: #555;
}
.wizard-exclude input {
  width: auto;
  margin: 0;
}
```

- [ ] **Step 3: Build the frontend to verify it compiles**

Run: `cd frontend && bun run build`
Expected: Build succeeds with no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/NewSessionPage.jsx frontend/src/App.css
git commit -m "feat(wizard): add 'Aussagen nicht prüfen' checkbox per participant"
```

---

## Task 3: Backend models — request/response field

**Files:**
- Modify: `backend/models.py:79-86` (`CreateSessionRequest`), `backend/models.py:141-154` (`SessionResponse`)
- Test: `backend/tests/test_api_sessions.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api_sessions.py`:

```python
async def test_create_session_accepts_excluded_speakers(client):
    resp = await client.post("/api/sessions", json={
        "title": "Talk",
        "guests": ["Caren Miosga (Moderatorin)", "Gast (CDU)"],
        "excluded_speakers": ["Caren Miosga"],
    })
    assert resp.status_code == 201
    assert resp.json()["excluded_speakers"] == ["Caren Miosga"]


async def test_create_session_defaults_excluded_speakers_empty(client):
    resp = await client.post("/api/sessions", json={"title": "T"})
    assert resp.status_code == 201
    assert resp.json()["excluded_speakers"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_api_sessions.py -k excluded_speakers -v`
Expected: FAIL — response has no `excluded_speakers` key (KeyError / assertion error). (This also depends on Tasks 4–5; that's fine — it stays red until the field is fully threaded.)

- [ ] **Step 3: Add the field to both models**

In `backend/models.py`, `CreateSessionRequest` (add after `conversation_type`):

```python
class CreateSessionRequest(BaseModel):
    """Request body for POST /api/sessions."""
    title: str
    date: str = ""
    guests: List[str] = []
    context: str = ""
    type: str = "show"
    conversation_type: str = "debate"
    excluded_speakers: List[str] = []
```

In `SessionResponse` (add after `conversation_type`):

```python
    conversation_type: str = "debate"
    excluded_speakers: List[str] = []
    auto_check: bool = False
```

- [ ] **Step 4: Commit (test stays red until Task 5)**

```bash
git add backend/models.py backend/tests/test_api_sessions.py
git commit -m "feat(models): add excluded_speakers to session request/response"
```

---

## Task 4: Backend database — column, migration, round-trip

**Files:**
- Modify: `backend/database.py` (sessions `CREATE TABLE` ~line 82, migrations block ~line 146, `_row_to_session` ~line 293, `add_session` ~line 310)
- Test: `backend/tests/test_database_sessions.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_database_sessions.py`:

```python
async def test_session_round_trips_excluded_speakers(db):
    await db.add_session({
        "session_id": "exc1",
        "title": "T",
        "guests": ["Caren Miosga (Moderatorin)"],
        "excluded_speakers": ["Caren Miosga"],
    })
    s = await db.get_session("exc1")
    assert s["excluded_speakers"] == ["Caren Miosga"]


async def test_session_defaults_excluded_speakers_empty(db):
    await db.add_session({"session_id": "exc2", "title": "T"})
    s = await db.get_session("exc2")
    assert s["excluded_speakers"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_database_sessions.py -k excluded_speakers -v`
Expected: FAIL — `KeyError: 'excluded_speakers'` from `_row_to_session` / missing column.

- [ ] **Step 3: Add the column to `CREATE TABLE sessions`**

In `backend/database.py`, the `CREATE TABLE IF NOT EXISTS sessions (...)` block, add the column after `conversation_type`:

```sql
                conversation_type TEXT NOT NULL DEFAULT 'debate',
                excluded_speakers TEXT NOT NULL DEFAULT '[]',
```

- [ ] **Step 4: Add the migration for existing tables**

In `backend/database.py`, right after the existing `conversation_type` sessions-migration block (the `for migration in ["ALTER TABLE sessions ADD COLUMN conversation_type ..."]` loop), add:

```python
        # Migration: add excluded_speakers to existing sessions tables
        for migration in [
            "ALTER TABLE sessions ADD COLUMN excluded_speakers TEXT NOT NULL DEFAULT '[]'",
        ]:
            try:
                await self.db.execute(migration)
                await self.db.commit()
            except Exception:
                pass  # Column already exists
```

- [ ] **Step 5: Read the column in `_row_to_session`**

In `_row_to_session`, add after the `conversation_type` line:

```python
            "conversation_type": row["conversation_type"],
            "excluded_speakers": json.loads(row["excluded_speakers"]),
```

- [ ] **Step 6: Write the column in `add_session`**

In `add_session`, update the INSERT column list, the placeholder count, and the values tuple. Change the column list to include `excluded_speakers` after `conversation_type`, add one more `?`, and insert the JSON-encoded value:

```python
        await self.db.execute(
            """INSERT INTO sessions
               (session_id, title, date, guests, context,
                type, conversation_type, excluded_speakers, auto_check, status, visibility, owner_code, created_at, ended_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session["session_id"],
                session.get("title", ""),
                session.get("date", ""),
                json.dumps(session.get("guests", []), ensure_ascii=False),
                session.get("context", ""),
                session.get("type", "show"),
                session.get("conversation_type", "debate"),
                json.dumps(session.get("excluded_speakers", []), ensure_ascii=False),
                int(bool(session.get("auto_check", False))),
                session.get("status", "active"),
                session.get("visibility", "private"),
                session.get("owner_code"),
                session.get("created_at", datetime.now().isoformat()),
                session.get("ended_at"),
            ),
        )
```

(Count check: 14 columns, 14 `?`, 14 values.)

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest backend/tests/test_database_sessions.py -k excluded_speakers -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/database.py backend/tests/test_database_sessions.py
git commit -m "feat(db): persist excluded_speakers on sessions with migration"
```

---

## Task 5: Backend sessions router — thread the field

**Files:**
- Modify: `backend/routers/sessions.py:17-36` (`create_session`)
- Test: covered by Task 3's `test_api_sessions.py` tests (now turns green).

- [ ] **Step 1: Add the field to the row dict in `create_session`**

In `backend/routers/sessions.py`, in the `row = {...}` dict, add after `conversation_type`:

```python
        "conversation_type": request.conversation_type,
        "excluded_speakers": request.excluded_speakers,
```

(`get_session` / `SessionResponse(**...)` already splats every dict key, so no further change is needed there.)

- [ ] **Step 2: Run the API tests to verify they pass**

Run: `uv run pytest backend/tests/test_api_sessions.py -k excluded_speakers -v`
Expected: PASS (both tests from Task 3).

- [ ] **Step 3: Commit**

```bash
git add backend/routers/sessions.py
git commit -m "feat(sessions): accept and return excluded_speakers"
```

---

## Task 6: Episode view-model carries `excluded_speakers`

**Files:**
- Modify: `config.py` (`Episode` dataclass ~line 43, `from_session_row` ~line 70, `episode_to_session_dict` ~line 241)
- Test: `backend/tests/test_config_sessions.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_config_sessions.py`:

```python
def test_from_session_row_reads_excluded_speakers():
    from config import Episode
    ep = Episode.from_session_row({"session_id": "s", "excluded_speakers": ["Caren Miosga"]})
    assert ep.excluded_speakers == ["Caren Miosga"]


def test_from_session_row_defaults_excluded_speakers_empty():
    from config import Episode
    ep = Episode.from_session_row({"session_id": "s"})
    assert ep.excluded_speakers == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_config_sessions.py -k excluded_speakers -v`
Expected: FAIL — `Episode` has no `excluded_speakers` attribute.

- [ ] **Step 3: Add the dataclass field**

In `config.py`, in the `Episode` dataclass, add after `conversation_type`:

```python
    type: str = "show"
    conversation_type: str = "debate"
    excluded_speakers: list[str] = field(default_factory=list)
    publish: bool = False
```

(`field` is already imported — it's used by `reference_links`.)

- [ ] **Step 4: Read it in `from_session_row`**

In `Episode.from_session_row`, add after `conversation_type=...`:

```python
            conversation_type=row.get("conversation_type", "debate"),
            excluded_speakers=row.get("excluded_speakers", []),
            publish=row.get("visibility") == "public",
```

- [ ] **Step 5: Write it in `episode_to_session_dict`**

In `episode_to_session_dict`, add after `conversation_type`:

```python
        "conversation_type": ep.conversation_type,
        "excluded_speakers": ep.excluded_speakers,
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest backend/tests/test_config_sessions.py -k excluded_speakers -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add config.py backend/tests/test_config_sessions.py
git commit -m "feat(config): carry excluded_speakers on Episode view-model"
```

---

## Task 7: Claim extraction — input field + threaded kwarg

**Files:**
- Modify: `backend/services/claim_extraction.py` (`ClaimExtractionInput` ~line 56, `extract_claims_async` ~line 131, `extract_async` ~line 145, `extract` ~line 153)
- Test: `backend/tests/test_claim_extraction.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_claim_extraction.py` (inside the same test class as `test_extract_passes_conversation_type`; mirror its `FunctionModel` capture pattern):

```python
    def test_claim_extraction_input_has_excluded_speakers(self):
        from backend.services.claim_extraction import ClaimExtractionInput
        assert "excluded_speakers" in ClaimExtractionInput.model_fields

    async def test_extract_passes_excluded_speakers(self, mock_claim_extractor):
        """excluded_speakers reaches the model as part of the user message."""
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.messages import ModelResponse
        from backend.services.claim_extraction import ClaimList

        captured = {}

        def capture(messages, info):
            captured["user_message"] = messages[-1].parts[-1].content
            return ModelResponse(parts=[])  # not reached for output; see note below

        # Reuse the same capture style already used by test_extract_passes_conversation_type.
        # If that test defines a local `capture` returning a ClaimList tool call, copy it verbatim
        # and only change the assertion below.
        with mock_claim_extractor.claim_extractor.override(model=FunctionModel(capture)):
            try:
                await mock_claim_extractor.extract_claims_async(
                    "Test transcript", ["Caren Miosga"],
                    excluded_speakers=["Caren Miosga"],
                )
            except Exception:
                pass  # we only care about the captured user_message
        assert "Caren Miosga" in captured["user_message"]
        assert "excluded_speakers" in captured["user_message"]
```

> **Implementer note:** Open `test_extract_passes_conversation_type` (≈ line 74) and copy its exact `capture`/`FunctionModel` mechanics for `test_extract_passes_excluded_speakers` rather than the sketch above — match the existing working pattern so the model returns a valid `ClaimList`. Keep the two assertions.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest backend/tests/test_claim_extraction.py -k excluded_speakers -v`
Expected: FAIL — `excluded_speakers` not in `model_fields`; `extract_claims_async` rejects the kwarg.

- [ ] **Step 3: Add the field to `ClaimExtractionInput`**

In `backend/services/claim_extraction.py`, in `ClaimExtractionInput`, add after `context`:

```python
    context: str = Field(default="", description="Thematischer Hintergrund des Gesprächs")
    excluded_speakers: list[str] = Field(default_factory=list, description="Namen von Personen, deren Aussagen NICHT extrahiert werden sollen (z. B. Moderator:in). Leere Liste = niemand wird ausgeschlossen.")
    transcript: str = Field(description="Transkript zur Analyse")
```

- [ ] **Step 4: Thread `excluded_speakers` through the three methods**

Update `extract_claims_async` signature and the `ClaimExtractionInput(...)` construction:

```python
    async def extract_claims_async(self, resolved_transcript: str, guests: list[str], context: str = "", previous_context: str | None = None, conversation_type: str = "", excluded_speakers: list[str] | None = None) -> List[ExtractedClaim]:
        """Extract claims from an already-resolved transcript. Skips speaker label resolution.

        This is the preferred entry point for the audio pipeline (called after resolve_labels_async).
        """
        logger.info(f"Extracting claims from resolved transcript ({len(resolved_transcript)} chars)")
        user_message = ClaimExtractionInput(
            conversation_type=conversation_type, guests=guests, context=context,
            excluded_speakers=excluded_speakers or [],
            transcript=resolved_transcript, previous_block_ending=previous_context,
        ).model_dump_json(indent=2)
        result = await self.claim_extractor.run(user_message)
        logger.info(f"Extraction complete: {len(result.output.claims)} claims found")
        return result.output.claims
```

Update `extract_async`:

```python
    async def extract_async(self, transcript: str, guests: list[str], context: str = "", previous_context: str | None = None, conversation_type: str = "", excluded_speakers: list[str] | None = None) -> List[ExtractedClaim]:
        """Extract claims, resolving speaker labels first (text-block pipeline entry point)."""
        logger.info(f"Extracting claims from transcript ({len(transcript)} chars)")
        if self.speaker_resolver:
            transcript = await self._resolve_speaker_labels_async(transcript, guests, conversation_type)
            logger.info(f"Speaker labels resolved ({len(transcript)} chars)")
        return await self.extract_claims_async(transcript, guests, context=context, previous_context=previous_context, conversation_type=conversation_type, excluded_speakers=excluded_speakers)
```

Update `extract` (sync wrapper):

```python
    def extract(self, transcript: str, guests: list[str], context: str = "", previous_context: str | None = None, conversation_type: str = "", excluded_speakers: list[str] | None = None) -> List[ExtractedClaim]:
        """Sync wrapper for extract_async()."""
        return asyncio.run(self.extract_async(transcript, guests, context=context, previous_context=previous_context, conversation_type=conversation_type, excluded_speakers=excluded_speakers))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest backend/tests/test_claim_extraction.py -k excluded_speakers -v`
Expected: PASS.

- [ ] **Step 6: Run the full extraction test file (no regressions)**

Run: `uv run pytest backend/tests/test_claim_extraction.py -m "not integration" -v`
Expected: PASS (all existing tests still green).

- [ ] **Step 7: Commit**

```bash
git add backend/services/claim_extraction.py backend/tests/test_claim_extraction.py
git commit -m "feat(extraction): thread excluded_speakers into ClaimExtractionInput"
```

---

## Task 8: Audio pipeline passes `excluded_speakers`

**Files:**
- Modify: `backend/routers/audio.py:134-198`
- Test: `backend/tests/test_audio_pipeline.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_audio_pipeline.py` (mirror `test_conversation_type_passed_to_extractor`):

```python
async def test_excluded_speakers_passed_to_extractor(mock_audio_file):
    """The session's excluded_speakers reaches extract_claims_async."""
    mock_transcription = MagicMock()
    mock_transcription.transcribe = MagicMock(return_value=("Sprecher A: Test.", 30.0))

    mock_extractor = MagicMock()
    mock_extractor.resolve_labels_async = AsyncMock(return_value="Caren Miosga: Test.")
    mock_extractor.extract_claims_async = AsyncMock(return_value=[])

    state.last_transcript_tail = None
    state.pipeline_events["exc-block"] = {"status": "processing"}

    await state.get_db().add_session({
        "session_id": "exc-sess", "title": "t",
        "guests": ["Caren Miosga (Moderatorin)"],
        "excluded_speakers": ["Caren Miosga"],
    })

    with patch("backend.routers.audio.get_transcription_service", return_value=mock_transcription), \
         patch("backend.routers.audio.get_claim_extractor", return_value=mock_extractor):
        await process_audio_pipeline_async("exc-block", mock_audio_file, "exc-sess", None)

    assert mock_extractor.extract_claims_async.call_args.kwargs.get("excluded_speakers") == ["Caren Miosga"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_audio_pipeline.py -k excluded_speakers -v`
Expected: FAIL — `excluded_speakers` kwarg not present in the call (`None`/absent).

- [ ] **Step 3: Read the field and pass it through**

In `backend/routers/audio.py`, after the `ep_conversation_type = ...` line (~137), add:

```python
    ep_conversation_type = ep.conversation_type if ep else "debate"
    ep_excluded_speakers = ep.excluded_speakers if ep else []
```

Then in the `extract_claims_async(...)` call (~194), add the kwarg:

```python
        claims = await claim_extractor.extract_claims_async(
            resolved_transcript, ep_guests,
            context=ep_context, previous_context=previous_context,
            conversation_type=ep_conversation_type,
            excluded_speakers=ep_excluded_speakers,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/test_audio_pipeline.py -k excluded_speakers -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/routers/audio.py backend/tests/test_audio_pipeline.py
git commit -m "feat(audio): pass session excluded_speakers into claim extraction"
```

---

## Task 9: Prompt — instruct the extractor to skip excluded speakers

**Files:**
- Modify: `prompts/claim_extraction.md`

> No unit test (prompt text). Soft enforcement is validated by the integration test in Task 10.

- [ ] **Step 1: Document the field in `<user_input>`**

In `prompts/claim_extraction.md`, in the `<user_input>` field list, add a line after the `context` line:

```
- context: Thematischer Hintergrund des Gesprächs
- excluded_speakers: Namen von Personen, deren Aussagen NICHT extrahiert werden sollen (kann leer sein)
- transcript: Das zu analysierende Transkript
```

- [ ] **Step 2: Add the skip rule inside `<Regeln>`**

In `prompts/claim_extraction.md`, inside the `<Regeln>` block (e.g. after the `</Zerlegung>` block, before `</Regeln>`), add:

```
<Ausschluss>
Wenn das Feld `excluded_speakers` nicht leer ist, extrahiere KEINE Behauptungen von diesen Personen. Überspringe deren Aussagen vollständig — auch wenn sie überprüfbare Fakten enthalten. Der Abgleich erfolgt über den im Transkript aufgelösten echten Namen. Ist `excluded_speakers` leer, schließe niemanden aus (Standardverhalten).
</Ausschluss>
```

- [ ] **Step 3: Sanity-check the prompt loads**

Run: `uv run python -c "from backend.utils import load_prompt; assert 'excluded_speakers' in load_prompt('claim_extraction.md'); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 4: Commit**

```bash
git add prompts/claim_extraction.md
git commit -m "feat(prompt): instruct extractor to skip excluded_speakers"
```

---

## Task 10: Integration test — excluded speaker's claim is dropped

**Files:**
- Modify: `backend/tests/integration/test_e2e_pipeline.py`

> Marked `integration`; requires `GEMINI_API_KEY`. Skips automatically without keys.

- [ ] **Step 1: Write the integration test**

Add to `backend/tests/integration/test_e2e_pipeline.py`:

```python
@pytest.mark.integration
async def test_excluded_speaker_claim_is_dropped(cheap_models):
    """An excluded speaker's obvious factual claim is skipped; a non-excluded one is kept."""
    skip_if_missing_keys()
    from backend.services.claim_extraction import ClaimExtractor

    # Already-resolved transcript (real names), so we test extraction directly.
    transcript = (
        "Caren Miosga: Deutschland hat 83 Millionen Einwohner.\n"
        "Heidi Reichinnek: Der Mindestlohn in Deutschland beträgt 12,82 Euro pro Stunde."
    )
    extractor = ClaimExtractor()
    claims = await extractor.extract_claims_async(
        transcript,
        guests=["Caren Miosga (Moderatorin)", "Heidi Reichinnek (Linke)"],
        excluded_speakers=["Caren Miosga"],
    )
    blob = " ".join(c.claim for c in claims).lower()
    # Excluded speaker's claim absent; non-excluded speaker's claim present.
    assert "83 millionen" not in blob and "einwohner" not in blob
    assert any("mindestlohn" in c.claim.lower() for c in claims)
```

- [ ] **Step 2: Run the integration test (requires keys)**

Run: `uv run pytest backend/tests/integration/test_e2e_pipeline.py -k excluded_speaker -m integration -v`
Expected: PASS when keys are present; SKIPPED otherwise. (Soft enforcement: if the LLM occasionally keeps the excluded claim, re-run; this is an accepted v1 limitation per the design's Risks section.)

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_e2e_pipeline.py
git commit -m "test(integration): assert excluded speaker's claim is dropped"
```

---

## Task 11: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Backend unit + frontend tests + lint + build**

```bash
uv run pytest backend/tests -m "not integration"
cd frontend && bun run test -- wizardLogic && bun run build && cd ..
uv run ruff check backend/
```

Expected: all green; ruff reports no new issues; frontend build succeeds.

- [ ] **Step 2: Manual smoke check of backward compatibility**

Run: `uv run pytest backend/tests/test_api_sessions.py backend/tests/test_database_sessions.py -v`
Expected: PASS — existing sessions without `excluded_speakers` default to `[]`; new column migration is idempotent.

- [ ] **Step 3: Final commit if anything was adjusted**

```bash
git add -A
git commit -m "chore: exclude-speaker feature verification pass"
```

(Skip if there is nothing to commit.)

---

## Self-Review Notes

- **Spec coverage:** UI checkbox (Task 2) ✓; `exclude` field + `buildSessionPayload` + `peopleStepValid` (Task 1) ✓; models (Task 3) ✓; DB column + migration + round-trip (Task 4) ✓; router (Task 5) ✓; Episode threading (Task 6) ✓; `ClaimExtractionInput` + kwarg threading (Task 7) ✓; audio pipeline (Task 8) ✓; prompt rule (Task 9) ✓; tests incl. integration (Tasks 1,3,4,6,7,8,10) ✓; backward compatibility (Task 11 step 2) ✓.
- **Spec deviation:** Design names the request model `SessionCreate`; the codebase uses `CreateSessionRequest`. Plan uses the real name. The text-block pipeline (`process_text_pipeline_async`) handles articles with no human speakers and keeps the default `excluded_speakers=[]`; only the audio pipeline wires a real value. The `extract_async`/`extract` signatures still accept the kwarg for completeness.
- **Type consistency:** `excluded_speakers: list[str]` everywhere; JSON-encoded as TEXT in SQLite like `guests`; Pydantic `List[str] = []` in models; dataclass uses `field(default_factory=list)`; extractor methods use `list[str] | None = None` → `or []` to avoid a mutable default.
