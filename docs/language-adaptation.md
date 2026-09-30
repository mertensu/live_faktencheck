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
SOURCES_DESCRIPTION = "Primärquellen mit URL und kurzem informativem Titel"
```

---

## 2. `prompts/*.md` — System prompts

Three prompt files drive the live lane. Translate and adapt all of them:

| File | What it does |
|---|---|
| `prompts/claim_extraction_streaming.md` | Window gate: decides whether a short window holds a checkable claim and extracts it |
| `prompts/claim_reformulation.md` | Jev gate path: rewrites a gated sentence into a standalone claim plus search queries |
| `prompts/fast_fact_checker.md` | Rates the claim against the search results (verdict, short reasoning, sources) |

The reformulator's search-query description (`ReformulatedClaim.search_queries` in
`backend/services/claim_extraction.py`) and the `FastVerdict.evidence` description in
`backend/services/fast_fact_checker.py` are German too. The fast checker's user message
labels (`Kontext der Sendung`, `Behauptung`, …) are built in `check_claim_async`.

---

## 3. Consistency verdict values

The four verdict strings (`"hoch"`, `"niedrig"`, `"unklar"`, `"keine Datenlage"`) are used as a `Literal` type in the LLM response schema and matched in the frontend for colors and labels. They must be consistent across:

**Backend** — change the `Literal` type and fallback values:

- `backend/services/fast_fact_checker.py` — `FastVerdict.consistency` field and the error
  fallback in `check_claim_async`:
  ```python
  consistency: Literal["hoch", "niedrig", "unklar", "keine Datenlage"]
  # → e.g. Literal["high", "low", "unclear", "no data"]
  ```
- `backend/utils.py` — default fallback in `build_fact_check_dict`:
  ```python
  "consistency": result_dict.get("consistency", "unklar")  # → "unclear"
  ```

**Frontend** — update the string comparisons in:

- `frontend/src/components/ClaimCard.jsx` — color and CSS class lookups
- `frontend/src/components/FactCheckStream.jsx` — filter chips and verdict classes
- `frontend/src/components/LiveTranscript.jsx` — verdict marks in the transcript

Also update the `CONSISTENCY_DESCRIPTION` string in `backend/lang.py` to match the new values you chose.

Stored rows keep the values they were written with, so a switch needs a data migration
if old results should still display correctly.

---

## 4. Database and API field names (optional)

The database columns and JSON API keys use German names (`sprecher`, `behauptung`, `begruendung`, `quellen`). These are internal — they never reach the LLM — so renaming them is optional but possible if you want a clean codebase.

Files to update if you rename them:

- `backend/database.py` — `CREATE TABLE` statement and all `INSERT`/`SELECT`/`UPDATE` queries
- `backend/models.py` — `FactCheck` Pydantic model
- `backend/utils.py` — `build_fact_check_dict()`
- `backend/routers/fact_checks.py`, `backend/services/streaming.py` — any dict accesses
- `frontend/src/components/FactCheckStream.jsx`, `LiveTranscript.jsx` — `behauptung`, `begruendung`, `quellen`

---

## 5. Frontend UI text

The UI pages contain German copy. If you want to fully localize the interface:

- `frontend/src/pages/AboutPage.jsx` — about/explainer text
- `frontend/src/pages/HomePage.jsx` — show listing page
- `frontend/src/pages/FactCheckPage.jsx` — main dashboard labels
- `frontend/src/components/Navigation.jsx` — nav links
- `frontend/src/components/Footer.jsx` — footer text
- `frontend/src/components/LiveTranscript.jsx`, `LiveTutorial.jsx` — live view and guide

---

## 6. Episode/show configuration

Show and episode metadata (titles, guest names, context strings) lives in `backend/config.py`. The `context` field on each episode (or session) is passed to the LLM — write it in your target language.

---

## Quick checklist

- [ ] Translate all strings in `backend/lang.py`
- [ ] Translate the three prompt files in `prompts/`
- [ ] Pick four verdict strings to replace `hoch / niedrig / unklar / keine Datenlage`
- [ ] Update `Literal[...]` and the error fallback in `backend/services/fast_fact_checker.py`
- [ ] Update the fallback value in `utils.py`
- [ ] Update string comparisons in `ClaimCard.jsx`, `FactCheckStream.jsx` and `LiveTranscript.jsx`
- [ ] (Optional) Rename German DB/API field names
- [ ] (Optional) Translate frontend UI copy
