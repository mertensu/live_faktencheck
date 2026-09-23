# Speaker Identification — Integration Plan (Live Fast Lane)

Status: **foundation done** (commit d62f1c4, dark behind `SPEAKER_ID_ENABLED`):
`services/speaker_id.py` (`SpeakerIdentifier.identify`, `load_voiceprints`, `pcm16_to_float32`),
`registry.get_speaker_identifier(guests)`, `benchmarks/enroll_voiceprints.py`, tests.
Streaming wiring done on `live-fast-lane` (§5.2, §6; track logic in
`services/speaker_track.py`), model baked into the image (§9). **Open: calibration** on
recorded episodes via the PR preview (§11). This document is written so implementation can start
cold in a fresh context. Prior work: offline spike done (`benchmarks/speaker_id_bench.py`),
result positive — see "Spike evidence".

## 1. Why

Speaker assignment in the live fast lane (`backend/services/streaming.py`) relies on
AssemblyAI streaming **diarization** (labels A/B/…) plus an LLM label→name pass. That is not
robust on single-mic TV audio:

- AssemblyAI v3 diarizes by **online reclustering**: labels are provisional and only get
  corrected **retroactively** via `SpeakerRevisionEvent` (delayed).
- A real run had every turn labelled "A" → all claims assigned to the same speaker.
- Even with correct reclustering (`max_speakers` set, `SpeakerRevision` handled, LLM
  resolution) the chain stays fragile and timing-sensitive.

## 2. Core decision

**Speaker identity is determined independently of AssemblyAI's diarization.**

- AssemblyAI still provides **ASR**: words, word timestamps, text, turn/sentence boundaries.
  That is reliable and remains the source for transcript + claims.
- We derive **identity** ourselves via **voiceprints**: a continuous PCM ring buffer, a
  background sliding window classifies continuously against the **episode's enrolled guests**
  (closed-set argmax, sherpa-onnx CAM++/ECAPA) → **our own speaker-over-time track**. Per claim
  we read the dominant speaker over the sentence's time span (known from word timestamps) from
  that track. **Not** tied to AssemblyAI turns/labels.
- AssemblyAI's `speaker_label` / `SpeakerRevisionEvent` are demoted to **fallback**: used only
  when the voiceprint is not confident (unknown speaker, too short/quiet, overlap).
- **LLM budget: zero LLM calls for speaker identity** when every episode speaker is enrolled.
  Voiceprints also name AssemblyAI's labels (§6.8), which replaces the LLM label→name
  resolver. That resolver runs **only** as a stopgap when the enrollment check (§5.3) finds
  speakers without a voiceprint. The only LLM call left in the fast lane is the fast check
  itself.

This makes identity robust against both wrong diarization labels *and* wrong turn clustering:
even if AssemblyAI calls everything "A" or glues two speakers into one turn, we classify the
audio directly. Remaining hard case: genuine overlap in the same sentence → mixed embedding →
low confidence → fallback (never a confident wrong name).

## 3. Data flow (target)

Important: an AssemblyAI **"turn" is a VAD/silence-based utterance boundary**, not a clean
speaker segment — an interruption without a pause puts two speakers in *one* turn, and the
`speaker_label` on it is the unreliable, delayed diarization. So we do **not** anchor identity
to turns; we build our **own speaker-over-time track**.

```
Browser PCM16 16k ──▶ StreamingSession.feed()
                        ├─▶ AssemblyAI (ASR: words + timestamps + text)   [ASR only]
                        └─▶ continuous PCM ring buffer (~10–15 s)          [NEW]

background task ──▶ sliding window over the buffer (e.g. 3 s window, 1 s hop)
   per window: embedding → argmax vs enrolled guests → (name|unknown, score)
   └─▶ compact SPEAKER TRACK: one entry per ~second (name|unknown), whole session
       (tiny). Audio is discarded after classification — only the track persists.

_flush_window() ──▶ gate returns claims with .source (original sentence)
   per claim: sentence → word time span [start_ms,end_ms]  (from reliable ASR timestamps)
              └─▶ read dominant speaker over the span from the TRACK (majority vote)
                    clear + confident → claim speaker; mixed/unknown → fallback
                    may land after the claim → rewrite plumbing (below)
```

## 4. Granularity & independence from AssemblyAI turns

- **Recommended v1: our own speaker track via sliding window** (above). Fully independent of
  AssemblyAI's turn/label concept; from AssemblyAI we take only **word timestamps** (reliable
  ASR) to know *when* a sentence was spoken. Detects a speaker change mid-turn instead of
  averaging it away. Cost: ~1 embedding/second, ~tens of ms CPU, in the background →
  negligible over 90 min.
- **Out of scope: the per-sentence slice variant** (sentence → PCM slice → one `identify` per
  claim). It can't see a speaker change within a span and the track costs little more. Build
  only the track.
- **Unknown/overlap**: falls below the cosine gate → fallback (never a confident wrong name);
  a *clearly* foreign voice is named as such (§6.9).

### 4.1 Sentence → word time span
The track lookup needs a sentence's **time span**, not its turn membership. `source` is a sentence
string from the **formatted** text; timestamps hang on the **words** (`words[].start/end`, raw
ASR tokens) — not a 1:1 match (case, punctuation, numbers). Mapping = find the word subsequence
whose normalized concatenation matches the sentence → `start = words[i].start`,
`end = words[j].end`. Fallback chain:
1. Normalize (lowercase, strip punctuation, collapse whitespace) → find the sentence as a
   substring of the normalized word stream → first/last word.
2. Else **anchor match** on the first/last few tokens.
3. Else a rough time estimate (window around the estimated position) → query the track.
4. Else skip ID → keep the label.

Expect step 1 to fail often on numbers: with `format_turns=True` the sentence reads "20 %"
while the words read "zwanzig Prozent" (same for dates, abbreviations). Claims are
disproportionately numeric, so step 2 (anchor match) is the **workhorse** — test it explicitly
with number-heavy sentences.

In the track approach this is uncritical: we only need an approximate span to read the
dominant speaker — not sample-accurate sentence boundaries.

## 5. New components

### 5.1 `backend/services/speaker_id.py` (new)
`SpeakerIdentifier`, lazy-loaded like the other AI services (`services/registry.py`):
- `__init__(model_path, voiceprints: dict[str, np.ndarray], threshold, min_seconds)`
- `identify(pcm_float32: np.ndarray, sr=16000) -> tuple[str|None, float]`:
  compute embedding (sherpa-onnx `SpeakerEmbeddingExtractor`), L2-normalize, cosine against all
  voiceprints, **argmax**. Returns `(name, top1)` if `top1 >= threshold` and audio duration
  `>= min_seconds`, else `(None, top1)`.
- Build the ONNX extractor once (num_threads from env), `provider="cpu"`.
- **No `soundfile` in the prod path**: live audio is already PCM (PCM16→float32 via numpy);
  `soundfile` stays bench-only (reading WAVs).

### 5.2 Continuous PCM ring buffer + speaker track in `StreamingSession`
- In `feed(audio)`: PCM16 bytes → float32, append to a **bounded, continuous** buffer; keep a
  running sample offset. Buffer only **~10–15 s** (enough for the sliding window + slack) —
  audio is discarded after classification, **not stored per turn**.
- Time axis: word timestamps (ms from session start) ↔ sample index = `ms/1000*16000`. We
  control the sample count ourselves. **Alignment invariant:** count samples in `feed` right
  next to `_client.stream(audio)` — only bytes actually sent to AssemblyAI advance the counter
  (if `_client is None` the audio is dropped for both). A reconnect resets AssemblyAI's clock →
  reset counter + buffer (track entries before the reset stay but are no longer addressable).
- **Background classifier** (own task): every ~1 s take the last 3 s window →
  - **Energy gate first:** RMS (or simple VAD) below a threshold → record the window as
    `None` without embedding. `min_seconds` only checks length, and 3 s of applause/room noise
    passes it.
  - Embed **off the event loop**: `await asyncio.to_thread(identifier.identify, pcm)`. The
    embedding is tens of ms of CPU; inline it would stall audio forwarding and WS events.
  - **Skip, don't queue:** if the previous step is still running, drop this tick (the next
    window overlaps anyway).
  - Append to the **speaker track** `self._spk_track: list[(win_start_ms, win_end_ms,
    name|None, score)]` — store the window's **span**, not a single timestamp (tiny,
    session-long; release audio afterwards). Maintain `self._track_covered_ms` = end of the
    newest classified window.
- `dominant_speaker(start_ms, end_ms) -> str|None`: vote over all track entries whose window
  **overlaps** the span (weight by overlap, optionally by score); `None` entries count against
  a clear majority; ambiguous/empty → `None`. Sentences shorter than the 3 s window still get
  every overlapping window, so they don't come out shifted by up to a second.
- **Pending lookups:** if `end_ms > _track_covered_ms` at query time, the answer isn't known
  yet. Keep `self._pending_spk: list[(pid, start_ms, end_ms)]`; after each classifier step,
  resolve every entry now covered → `_apply_voiceprint(pid, name)` (§6.5). Drain/give up on
  remaining entries at `stop()`.

### 5.3 Voiceprint store + enrollment (offline)
- Store: `backend/data/voiceprints/<Name>.npy` (unit vector) **or** a small JSON/SQLite
  `{name: [floats]}`. Loaded at session start, **filtered to the episode's speakers**.
  - **Pass `ep.speakers`, not `ep.guests`.** `guests` entries carry roles
    (`"Sandra Maischberger (Moderatorin)"`), while `load_voiceprints` compares against the file
    stem (`Sandra Maischberger.npy`) → with raw `guests` nothing matches and
    `get_speaker_identifier` silently returns `None`. `routers/stream.py:81` currently passes
    `ep.guests` to the session, so strip roles when calling the factory.
  - The moderator is already in `guests` (listed first) → **enroll moderators** as a matter
    of course: recurring, trivially enrolled once, and otherwise all moderator speech falls
    back to the weak label path.
  - Closed set = this episode's speakers → few confusions; non-guests fall through the gate.
- **Where they live: the server's data dir, never git.** The repo is public and voiceprints are
  biometric data of real people. `backend/data/voiceprints/*.npy` stays git-ignored; on the
  VPS they live in `/opt/fact_check/backend/data/voiceprints` (prod) and
  `/opt/fact_check/staging/data/voiceprints` (staging), which the containers already mount as
  `/app/backend/data`, so the default `SPEAKER_ID_VOICEPRINTS_DIR` resolves there. The
  maintainer copies new prints there during show prep.
- Enrollment: **offline**, via an extended bench (`benchmarks/enroll_voiceprints.py`, new):
  reads `enroll/<Name>/*.wav`, averages embeddings, writes the store. No enrollment in the live
  path.
- Pre-show enrollment (a short live clip per guest) is a later addition; v1 = store from public
  clips.
- **Enrollment is show prep, checked automatically.** A guest without a voiceprint silently
  falls back to the weak path, so coverage must be visible:
  - Adding an episode to `EPISODES` includes enrolling any new speaker from 1–2 public clips
    (`enroll_voiceprints.py`); note this in the episode-config docs.
  - At session start, compute `missing = ep.speakers − voiceprints`. Log it and emit a
    `speaker_id_status` event `{enrolled: [...], missing: [...]}` so the admin UI shows
    "no voiceprint for X" before the show starts.
  - `missing` also decides whether the LLM resolver runs at all (§6.8).

## 6. Changes in `streaming.py` (concrete touch points)

1. `start()`: no ASR config change needed (words + timestamps are in `TurnEvent.words`,
   `Word.start/end`). `speaker_labels`/`max_speakers` can stay (fallback path).
2. `_on_turn` → `handle_turn(...)`: pass `words` (list with timestamps) through; carry them on
   the window buffer entries (for the sentence → time span). **Prerequisite for everything
   else** — today `_on_turn` forwards only transcript/end_of_turn/speaker_label/turn_order.
   Also update `words` in the **re-emission branch** (a repeated final for a known
   `turn_order` replaces `text` in `_turns` and the buffer entry — `words` must be replaced
   alongside, or the span mapping aligns new text against stale words).
3. `feed`: feed the continuous PCM ring buffer and advance the sample counter next to
   `_client.stream` (alignment invariant, 5.2); the background classifier builds the speaker
   track. Start the classifier task in `start()`, cancel it in `stop()`.
4. `_flush_window`: per claim, `source` sentence → word time span `[start_ms,end_ms]` (4.1).
   **Resolve the speaker before the fast check, not after:** `check_claim_async(speaker=...)`
   feeds the name into the check, so a wrong name ends up in the *reasoning* (`begruendung`),
   and a later rewrite only fixes `sprecher`. A claim reaches the flush seconds after it was
   spoken (window of 2 sentences / 3 turns + gate), so the track normally already covers it.
   Hence, inside the per-claim task (`_check_and_store`, already off the flush path):
   - if `end_ms <= _track_covered_ms` → `dominant_speaker(span)` now;
   - else wait for coverage with a **bounded** timeout (~1 s, env-tunable `SPEAKER_ID_WAIT_MS`, tune on recorded episodes; an
     `asyncio.Event`/condition set by the classifier after each step), then query;
   - on timeout → store with the best-known fallback speaker and register the claim in
     `_pending_spk` (5.2) → resolved later via rewrite (point 5).
5. **Rewrite plumbing** (already exists): `_rewrite_speaker(pid, name)` + event
   `claim_speaker_update` (frontend `useAudioStream.js` already handles it). Late voiceprint
   results go through a thin `_apply_voiceprint(pid, name)` that rewrites and **locks** the
   claim (below).
6. **Per-claim speaker fallback chain**: voiceprint over the sentence span (if confident) →
   `_speaker_map[label]` (filled by voiceprint label votes, §6.8; by the LLM only for
   unenrolled speakers) → raw diarization label. **This precedence must be enforced**, because
   two existing paths rewrite speakers on their own and would clobber a voiceprint name:
   - `handle_speaker_revision` rewrites every pid in `_turn_claims[turn_order]`;
   - `_apply_map_to_pending` rewrites every pid in `_label_claims[label]`.
   Rule: a claim with a confident voiceprint name is **not registered** in `_turn_claims` /
   `_label_claims` (and is removed from them when a late voiceprint result arrives). Keep a
   `self._voiceprint_pids: set[int]` and have both paths skip members as a second guard. A
   voiceprint `None` (unknown/overlap/too quiet) leaves the claim on the label paths as today.
7. `_match_turn` stays: it still provides `(turn_order, label)` for the fallback chain. It
   is also the natural place to pick up the matched entry's `words` for the span mapping.
8. **Voiceprint label naming (replaces the LLM resolver).** For each finalized turn, read
   `dominant_speaker(turn span)` from the track and count a vote `label → name`
   (`self._label_votes[label][name]`). When a label has ≥ N confident votes (~3) with a clear
   majority (~80 %), set `_speaker_map[label] = name` and call the existing
   `_apply_map_to_pending`. Re-evaluate on every vote, so AssemblyAI reclustering is followed.
   No new plumbing: `_speaker_map`, `_label_claims`, `handle_speaker_revision` and the live
   `display_speaker` all keep working, now fed by voiceprints instead of an LLM. Names within
   seconds instead of after ~1 min of transcript. If labels are garbage (everything "A"),
   votes are mixed → no mapping → the per-sentence span (point 6, first link) still names
   most claims.
   - **LLM resolver gating:** `_maybe_resolve_speakers` runs only when speaker ID is off
     (today's behaviour) or `missing` (§5.3) is non-empty; then only labels without a
     voiceprint mapping are taken from its result. All speakers enrolled → **no LLM call**.
9. **Unknown voice as a signal.** Loud enough, span covered, and **every** overlapping window
   below a low `SPEAKER_ID_UNKNOWN_THRESHOLD` (well under the accept threshold; calibrate on
   recorded episodes) → a clearly foreign voice: clip (Einspieler), caller, audience. Set `sprecher` to
   the German "unknown speaker" string (in `backend/lang.py`, per convention), don't fall back
   to a guest label, and mark the claim so the admin UI can flag it. The claim is still
   checked. Between the two thresholds ("unsure", e.g. overlap) → normal fallback chain.
   Wrongly crediting a clip's statement to a guest is the most damaging mistake here, and this
   costs nothing extra.

## 7. Gate / thresholds (from the spike, calibratable)

- **Primary gate: absolute cosine `top1 >= ~0.55–0.60`.** In the spike this cleanly separated
  unknown speakers (0% unknown accepted) from enrolled ones (known top1 ≥ 0.68).
- Argmax classification was 100% correct even with 3 similar voices and 2 s segments.
- **Top1–Top2 margin** as a secondary confidence signal (optional): large margin = unambiguous.
  In the spike the absolute cosine was the more reliable unknown filter; margin is complementary.
- `min_seconds` (~1.5 s): skip shorter/quieter sentences → fallback.
- **Recalibrate the threshold on real data**: the per-sentence (pooled) distribution differs
  from the bench's fixed windows.

## 8. Configuration (env, feature flag)

- `SPEAKER_ID_ENABLED` (default `false`) — gates the whole path; ships dark.
- `SPEAKER_ID_WAIT_MS` (default ~1000) — bounded wait for track coverage (§6.4).
- `SPEAKER_ID_UNKNOWN_THRESHOLD` — "clearly foreign voice" cutoff (§6.9), calibrated on recorded episodes.
- `SPEAKER_ID_MODEL` — path to the .onnx (baked into the image, see below).
- `SPEAKER_ID_THRESHOLD` (default ~0.55).
- `SPEAKER_ID_MIN_SECONDS` (default 1.5).
- `SPEAKER_ID_NUM_THREADS` (default 1).
- `SPEAKER_ID_VOICEPRINTS_DIR` (default `backend/data/voiceprints`).
- Track tuning (defaults in `streaming.py`): `SPEAKER_ID_WINDOW_MS` (3000), `SPEAKER_ID_HOP_MS`
  (1000), `SPEAKER_ID_BUFFER_MS` (15000), `SPEAKER_ID_MIN_RMS` (0.01, energy gate),
  `SPEAKER_ID_MAJORITY` (0.6, span vote), `SPEAKER_ID_UNKNOWN_THRESHOLD` (0.35),
  `SPEAKER_ID_LABEL_MIN_VOTES` (3), `SPEAKER_ID_LABEL_MAJORITY` (0.8).
- Import sherpa-onnx **lazily** in `speaker_id.py`, so a disabled flag never loads the ONNX
  stack.

## 9. Deployment decision

**Recommendation: in-process** (embedding inside the backend container), not a sidecar.
- Load is small: one embedding per second (track), ~tens of ms CPU, off
  the hot path. No IPC / extra ops.
- Prod dependencies: move `sherpa-onnx`, `onnxruntime`, `numpy` from the `bench` group into the
  **main dependencies** (or a `speakerid` extra that the Dockerfile installs). `soundfile` stays
  bench-only. Image grows ~200 MB (onnxruntime); acceptable.
- **Model file** (~27 MB) baked into the image (reproducible) rather than fetched at runtime:
  download it in the Dockerfile from the pinned k2-fsa release URL with a sha256 check (keeps
  27 MB out of git), to e.g. `/app/models/`. **Not** under `backend/data/` (hidden by the data
  bind mount). Set `SPEAKER_ID_MODEL` to that path.
- macOS dev note (local only): the sherpa-onnx wheel doesn't find `libonnxruntime.dylib` —
  needs a symlink (documented in the `speaker_id_bench.py` header). No issue on Linux/CI/VPS.
- Consider a sidecar only if CPU contention with the fact-checkers becomes real.

## 10. Tests

- Unit: inject `SpeakerIdentifier` as a stub into `StreamingSession` (like `gate`/`fast_checker`):
  `identify(pcm)->(name,score)`. Cases: confident → label overridden; unknown/None → label kept;
  async ID lands after the claim → `claim_speaker_update` + DB `sprecher` rewritten. **No
  onnxruntime in unit tests** (stub).
- **Precedence:** voiceprint-named claim + later `handle_speaker_revision` / speaker-map
  resolution → name is **not** overwritten; voiceprint `None` → label paths still rewrite.
- **Resolve-before-check:** track already covers the span → `fast_checker` is called with the
  voiceprint name (assert on the stub's `speaker` arg); coverage arrives within the timeout →
  same; timeout → fallback name, then late rewrite via `_pending_spk`.
- Classifier: silent window (energy gate) → `None` without calling `identify`; overlapping
  windows vote correctly for a sentence shorter than the window; a slow `identify` makes the
  next tick skip rather than queue.
- Re-emitted final with changed text → buffer entry carries the new `words`.
- Factory filter: `get_speaker_identifier(ep.speakers)` matches `<Name>.npy`; role-annotated
  names do not (guards against the `ep.guests` pitfall, §5.3).
- **Label naming:** consistent votes → `_speaker_map[label]` set + pending claims rewritten;
  mixed votes → no mapping; majority flips after reclustering → mapping follows.
- **LLM gating:** all speakers enrolled → resolver stub never called; one missing → called,
  but voiceprint-mapped labels are not overwritten.
- **Unknown voice:** all windows below the unknown threshold → unknown string + flag, no label
  fallback; between thresholds → normal fallback.
- Test sentence → word span mapping separately (text alignment against `words`), including
  number-heavy sentences where only the anchor match succeeds (§4.1).
- Accuracy stays in the **offline bench** (`benchmarks/`, real audio), not in unit tests.

## 11. Rollout

1. Merge behind `SPEAKER_ID_ENABLED=false` (dark).
2. Enroll moderators + recurring guests (build the store), bake the model into the image.
3. **Calibrate through the PR preview link** (the project has no live users yet, so no shadow
   mode; no local `start_dev.sh` either). PR #9 (`live-fast-lane`) → CI pushes
   `:branch-live-fast-lane` → staging must track that branch
   (`deploy/staging-track.sh live-fast-lane`, maintainer, once) → the preview link on the PR
   talks to staging. Prerequisites on staging:
   - `SPEAKER_ID_ENABLED=true` and `SPEAKER_ID_MODEL` in `/opt/fact_check/.env.staging`;
   - the model in the image (§9), **not** under `backend/data/`: staging bind-mounts its data
     dir over `/app/backend/data`, which hides anything baked there;
   - voiceprints in `/opt/fact_check/staging/data/voiceprints/` (§5.3).
   Play 2–3 recorded episodes (Mediathek) into the preview's live audio input, ideally ones
   with crosstalk and clips of other people (Einspieler).
   **Reading results needs Logfire:** staging logs are otherwise only reachable over SSH, and
   plain `logger.info` does **not** reach Logfire (no logging handler is installed). So emit
   one `logfire.info` per claim: `speaker, source (span|label_vote|llm|label|unknown),
   voiceprint_name, score, span, waited_ms, session_id`. Logfire is already a dependency and
   configured; confirm `LOGFIRE_TOKEN` is set in `.env.staging` (it was copied from prod).
   Compare against the actual speakers and set the accept threshold, the unknown threshold and
   `SPEAKER_ID_WAIT_MS`. Also check CPU cost and that the event loop doesn't stall.
4. Enable on prod.

## 12. Open risks

- **Genuine overlap/crosstalk** in the same sentence → mixed embedding → low confidence →
  fallback. Safe degradation, but watch it in live operation (not measurable offline with clean
  clips).
- **Threshold calibration** on pooled per-sentence embeddings vs. the bench's fixed windows.
- **Enrollment domain gap** (public clips vs. studio) — partly validated in the spike as
  cross-recording (margin shrinks with similar voices); keep watching on real data.
- **Buffer memory**: audio ring buffer only ~10–15 s (release after classification); the speaker
  track itself is tiny (one entry/second) and may stay session-long.
- **Sentence → span alignment**: needs robust text alignment (the reformulator changes the claim
  text, but `source` is the original sentence → matchable against `words`).

## 12a. Future: moderator enrollment (not now)

For now only the maintainer creates voiceprints (offline, §5.3). Later, moderators may need to
add guests without a voiceprint. Decided scope for that: **before the show only**, never live
(checking starts immediately, there is no time to enroll mid-show). Shape: an admin-UI upload
of a clean clip per guest; the browser decodes it to 16 kHz PCM (same as the live stream), the
backend embeds it with the existing extractor and writes `<Name>.npy` to the data dir. Sessions
load prints at start, so no mid-session hot-add or retroactive re-scoring is needed. Before
building it: legal basis for storing biometric data (GDPR Art. 9), deletion, per-show storage.

## 13. Spike evidence (context for implementation)

- Model: `3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx` (CAM++, dim=192), from the
  k2-fsa release tag `speaker-recongition-models` (the typo in the tag is real).
- Bench: `benchmarks/speaker_id_bench.py`, data (git-ignored) under
  `benchmarks/data/speaker_id/{enroll,eval}/<Name>/*.wav` (16k mono).
- Results (Connemann/Dröge/Maischberger, 1 enroll clip each, different YouTube recordings):
  - 3 speakers: argmax accuracy **100%**; impostor cosine rises with similar (female) voices
    (max 0.55), margin shrinks to ~0.13 but stays separated.
  - Short segments 2/3/5 s: accuracy **100%**, top1–top2 margin stable ≥ 0.13.
  - Unknown rejection (intruder not enrolled): gate `cos>=0.55` → **0% unknown**, 83% known
    accepted (rest falls back to the label).
- Verdict: green light; the hard untested remainder is genuine crosstalk.
