# Adapting Live Faktencheck for Another Language

This guide explains what to change to run the fact-checker in a language other than German.

---

## Overview of language-specific parts

| Layer | What's language-specific | Where to change it |
|---|---|---|
| LLM field descriptions | Labels guiding the model's structured output | `backend/lang.py` |
| LLM prompts | System instructions for extraction and fact-checking | `prompts/*.md` |
| Consistency values | The four verdict strings used throughout the stack | Multiple files (see below) |
| DB field names | Column names are German words | `backend/database.py` (optional) |
| Frontend UI | Labels, verdict display, about page | `frontend/src/` |

---

## 1. `backend/lang.py` — LLM field descriptions

This is the primary file to change. It contains the German descriptions that are injected into Pydantic model fields and sent to the LLM as part of its structured output schema.

```python
# Translate all strings in this file to your target language.
CLAIM_NAME_DESCRIPTION = "Vollständiger Name des Sprechers (Eigenname)."
CLAIM_TEXT_DESCRIPTION = "Die deutschsprachige dekontextualisierte Behauptung."
SOURCE_URL_DESCRIPTION = "URL zur Quelle"
SOURCE_TITLE_DESCRIPTION = "Kurze informative Beschreibung der Quelle, ..."
CONSISTENCY_DESCRIPTION = """Empirische Konsistenz der Behauptung. ..."""
EVIDENCE_DESCRIPTION = "Detaillierte und gut strukturierte deutschsprachige Begründung"
SOURCES_DESCRIPTION = "Primärquellen mit URL und kurzem informativem Titel"
```

---

## 2. `prompts/*.md` — System prompts

Four prompt files drive the LLM pipeline. Translate and adapt all of them:

| File | What it does |
|---|---|
| `prompts/claim_extraction.md` | Instructs the model to extract factual claims from a transcript |
| `prompts/fact_checker.md` | Instructs the ReAct agent to research and verify a claim |
| `prompts/speaker_labels.md` | Resolves generic speaker labels (e.g. "Speaker A") to real names |
| `prompts/claim_selection.md` | Selects the most fact-checkable claims in autopilot mode |

The English originals are in `prompts/en/` for reference.

**Important:** `claim_extraction.md` and `fact_checker.md` contain `{input_schema}` and `{current_date}` placeholders that are filled in at runtime — keep those exactly as-is.

---

## 3. Consistency verdict values

The four verdict strings (`"hoch"`, `"niedrig"`, `"unklar"`, `"keine Datenlage"`) are used as a `Literal` type in the LLM response schema and matched in the frontend for colors and scoring. They must be consistent across:

**Backend** — change the `Literal` type and fallback values:

- `backend/services/fact_checker.py` — `FactCheckResponse.consistency` field:
  ```python
  consistency: Literal["hoch", "niedrig", "unklar", "keine Datenlage"]
  # → e.g. Literal["high", "low", "unclear", "no data"]
  ```
- `backend/services/fact_checker.py` — error fallback:
  ```python
  "consistency": "unklar"  # → "unclear"
  ```
- `backend/utils.py` — default fallback in `build_fact_check_dict`:
  ```python
  "consistency": result_dict.get("consistency", "unklar")  # → "unclear"
  ```

**Frontend** — update the string comparisons in two components:

- `frontend/src/components/ClaimCard.jsx` — color and CSS class lookups:
  ```js
  if (lower === 'hoch') ...
  if (lower === 'niedrig') ...
  if (lower === 'unklar') ...
  // keine Datenlage → fallback
  ```
- `frontend/src/components/SpeakerColumns.jsx` — score calculation and tooltip text:
  ```js
  c.consistency?.toLowerCase() === 'hoch'
  c.consistency?.toLowerCase() === 'niedrig'
  c.consistency?.toLowerCase() === 'unklar'
  ```

Also update the `CONSISTENCY_DESCRIPTION` string in `backend/lang.py` to match the new values you chose.

---

## 4. Database and API field names (optional)

The database columns and JSON API keys use German names (`sprecher`, `behauptung`, `begruendung`, `quellen`). These are internal — they never reach the LLM — so renaming them is optional but possible if you want a clean codebase.

Files to update if you rename them:

- `backend/database.py` — `CREATE TABLE` statement and all `INSERT`/`SELECT`/`UPDATE` queries
- `backend/models.py` — `FactCheck` Pydantic model
- `backend/utils.py` — `build_fact_check_dict()`
- `backend/routers/fact_checks.py`, `claims.py`, `audio.py` — any dict accesses
- `frontend/src/components/ClaimCard.jsx` — `claim.behauptung`, `claim.begruendung`
- `frontend/src/components/ClaimDetailOverlay.jsx` — same fields

---

## 5. Frontend UI text

The UI pages contain German copy. If you want to fully localize the interface:

- `frontend/src/pages/AboutPage.jsx` — about/explainer text
- `frontend/src/pages/HomePage.jsx` — show listing page
- `frontend/src/pages/FactCheckPage.jsx` — main dashboard labels
- `frontend/src/components/Navigation.jsx` — nav links
- `frontend/src/components/Footer.jsx` — footer text
- `frontend/src/components/SpeakerColumns.jsx` — tooltip strings like `"Behauptungen korrekt"`, `"nicht gewertet"`, etc.

---

## 6. Episode/show configuration

Show and episode metadata (titles, guest names, context strings) lives in `backend/config.py`. The `info` field on each episode is passed as context to the LLM — write it in your target language.

---

## Quick checklist

- [ ] Translate all strings in `backend/lang.py`
- [ ] Translate the four prompt files in `prompts/`
- [ ] Pick four verdict strings to replace `hoch / niedrig / unklar / keine Datenlage`
- [ ] Update `Literal[...]` in `backend/services/fact_checker.py`
- [ ] Update fallback values in `fact_checker.py` and `utils.py`
- [ ] Update string comparisons in `ClaimCard.jsx` and `SpeakerColumns.jsx`
- [ ] (Optional) Rename German DB/API field names
- [ ] (Optional) Translate frontend UI copy
