# Speaker Identification — Integration Plan (Live Fast Lane)

Status: planned, not yet implemented. This document is written so implementation can start
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
- **Simpler fallback variant: slice per claim `source` sentence** (sentence → word span → PCM
  slice → `identify`). Fewer embeddings, but *one* pooled embedding per sentence → won't see a
  speaker change within the span. Fine as an intermediate step; swappable behind the same
  interface.
- **Unknown/overlap**: in both variants falls below the cosine gate → fallback (never a
  confident wrong name).

### 4.1 Sentence → word time span
Both variants need a sentence's **time span**, not its turn membership. `source` is a sentence
string from the **formatted** text; timestamps hang on the **words** (`words[].start/end`, raw
ASR tokens) — not a 1:1 match (case, punctuation, numbers). Mapping = find the word subsequence
whose normalized concatenation matches the sentence → `start = words[i].start`,
`end = words[j].end`. Fallback chain:
1. Normalize (lowercase, strip punctuation, collapse whitespace) → find the sentence as a
   substring of the normalized word stream → first/last word.
2. Else **anchor match** on the first/last few tokens.
3. Else a rough time estimate (window around the estimated position) → query the track.
4. Else skip ID → keep the label.
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
  control the sample count ourselves.
- **Background classifier** (own task): every ~1 s embed the last 3 s window → `identify` →
  append to the **speaker track** `self._spk_track: list[(t_sec, name|None, score)]` (tiny,
  session-long; release audio afterwards).
- `dominant_speaker(start_ms, end_ms) -> str|None`: majority/weighted vote of the track entries
  in the span; ambiguous/empty → `None`.
- Fallback variant without a track: `_slice(start_ms,end_ms)` + a single `identify` per claim
  sentence.

### 5.3 Voiceprint store + enrollment (offline)
- Store: `backend/data/voiceprints/<Name>.npy` (unit vector) **or** a small JSON/SQLite
  `{name: [floats]}`. Loaded at session start, **filtered to `episode.guests`** (+ optionally
  the moderator). Closed set = this episode's guests → few confusions, non-guests fall through
  the gate correctly.
- Enrollment: **offline**, via an extended bench (`benchmarks/enroll_voiceprints.py`, new):
  reads `enroll/<Name>/*.wav`, averages embeddings, writes the store. No enrollment in the live
  path.
- Pre-show enrollment (a short live clip per guest) is a later addition; v1 = store from public
  clips.

## 6. Changes in `streaming.py` (concrete touch points)

1. `start()`: no ASR config change needed (words + timestamps are in `TurnEvent.words`,
   `Word.start/end`). `speaker_labels`/`max_speakers` can stay (fallback path).
2. `_on_turn` → `handle_turn(...)`: pass `words` (list with timestamps) through; carry them on
   the window buffer entries (for the sentence → time span).
3. `feed`: feed the continuous PCM ring buffer; the background classifier builds the speaker
   track (5.2).
4. `_flush_window`: per claim, `source` sentence → word time span `[start_ms,end_ms]` (4.1) →
   read `dominant_speaker(span)` from the track. Store the claim immediately with the
   best-known speaker (label/LLM); the track result arrives at the same time or shortly after →
   set it via rewrite.
5. **Reuse the rewrite plumbing** (already exists): `_turn_claims`/`_label_claims`,
   `_rewrite_speaker(pid, name)`, event `claim_speaker_update` (frontend `useAudioStream.js`
   already handles it). Voiceprint ID hooks into the same retroactive-rewrite path.
6. **Per-claim speaker fallback chain**: voiceprint (if confident) → LLM resolution
   `speaker_map[label]` → raw diarization label.

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
- `SPEAKER_ID_MODEL` — path to the .onnx (baked into the image, see below).
- `SPEAKER_ID_THRESHOLD` (default ~0.55).
- `SPEAKER_ID_MIN_SECONDS` (default 1.5).
- `SPEAKER_ID_NUM_THREADS` (default 1).
- `SPEAKER_ID_VOICEPRINTS_DIR` (default `backend/data/voiceprints`).
- Import sherpa-onnx **lazily** in `speaker_id.py`, so a disabled flag never loads the ONNX
  stack.

## 9. Deployment decision

**Recommendation: in-process** (embedding inside the backend container), not a sidecar.
- Load is small: one embedding per second (track) or per claim sentence, ~tens of ms CPU, off
  the hot path. No IPC / extra ops.
- Prod dependencies: move `sherpa-onnx`, `onnxruntime`, `numpy` from the `bench` group into the
  **main dependencies** (or a `speakerid` extra that the Dockerfile installs). `soundfile` stays
  bench-only. Image grows ~200 MB (onnxruntime); acceptable.
- **Model file** (~27 MB) `COPY`-ed into the image (reproducible) rather than fetched at runtime.
- macOS dev note (local only): the sherpa-onnx wheel doesn't find `libonnxruntime.dylib` —
  needs a symlink (documented in the `speaker_id_bench.py` header). No issue on Linux/CI/VPS.
- Consider a sidecar only if CPU contention with the fact-checkers becomes real.

## 10. Tests

- Unit: inject `SpeakerIdentifier` as a stub into `StreamingSession` (like `gate`/`fast_checker`):
  `identify(pcm)->(name,score)`. Cases: confident → label overridden; unknown/None → label kept;
  async ID lands after the claim → `claim_speaker_update` + DB `sprecher` rewritten. **No
  onnxruntime in unit tests** (stub).
- Test sentence → word span mapping separately (text alignment against `words`).
- Accuracy stays in the **offline bench** (`benchmarks/`, real audio), not in unit tests.

## 11. Rollout

1. Merge behind `SPEAKER_ID_ENABLED=false` (dark).
2. Enroll recurring guests (build the store), bake the model into the image.
3. Enable on **staging** (branch auto-deploy is live), record a real session, check voiceprint
   IDs against reality, recalibrate the threshold.
4. Only then enable on prod.

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
