"""
Speaker-identification spike (SG-8): can voiceprints beat label→name resolution?

The live lane assigns a claim's speaker via AssemblyAI diarization labels (A/B/…) plus
an LLM label→name pass. On single-mic TV audio that is not robust: labels start wrong and
resolution lands seconds late (see [[streaming-speaker-diarization]]). This benchmark tests
the alternative — match each utterance's *voiceprint* against enrolled known speakers with
sherpa-onnx (ECAPA/CAM++ embedding + cosine) — OFFLINE, before we touch the live pipeline.

What it measures, on YOUR audio:
  1. Accuracy: for each labelled eval clip, is the top cosine match the right person?
  2. Separation: same-speaker cosine vs impostor cosine — the gap that a threshold lives in.
  3. A threshold sweep, so we pick an accept/"unknown" band the way the Jev gate did
     (p>=0.85 / <=0.30), not a single guessed cut.

This is a spike: it does not import or change any backend code. If it shows good
separation on real episode audio, the plan is to reuse the retroactive-rewrite plumbing
already in streaming.py (claim_speaker_update / _label_claims / _turn_claims) and feed
voiceprint IDs into the speaker slot instead of / alongside the LLM resolution.

──────────────────────────────────────────────────────────────────────────────
SETUP

1. Install the opt-in bench deps (kept out of the prod image):
     uv sync --group bench

2. Download a sherpa-onnx speaker-embedding model (CPU, ~10-30 MB), e.g. one of:
     - 3dspeaker_speech_campplus_sv_zh_en_16k-common   (CAM++, zh+en, generalises to DE)
     - wespeaker_en_voxceleb_resnet34_LM                (VoxCeleb ResNet34)
   from https://github.com/k2-fsa/sherpa-onnx/releases (tag: speaker-recognition-models)
   or huggingface `csukuangfj`. Point SPK_MODEL at the .onnx file.

3. Lay out 16 kHz mono WAVs (convert anything else:  ffmpeg -i in -ar 16000 -ac 1 out.wav):
     benchmarks/data/speaker_id/
       enroll/<Name>/*.wav   # reference voiceprint clips per known person (public
                             #   speeches/interviews are fine to start; 15-60 s each)
       eval/<Name>/*.wav     # held-out labelled utterances to score (e.g. slices of the
                             #   recorded Connemann/Dröge episode you stream in tests)

RUN
     SPK_MODEL=/path/to/model.onnx uv run --group bench python benchmarks/speaker_id_bench.py
──────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
from pathlib import Path

import numpy as np
import soundfile as sf
import sherpa_onnx

SR = 16000
DATA = Path(__file__).parent / "data" / "speaker_id"
ENROLL_DIR = Path(os.getenv("SPK_ENROLL_DIR", DATA / "enroll"))
EVAL_DIR = Path(os.getenv("SPK_EVAL_DIR", DATA / "eval"))
MODEL = os.getenv("SPK_MODEL", "")
NUM_THREADS = int(os.getenv("SPK_NUM_THREADS", "1"))


# ---- audio -----------------------------------------------------------------
def load_wav(path: Path) -> np.ndarray:
    """Return float32 mono samples at 16 kHz for a WAV of any rate/channels."""
    samples, sr = sf.read(str(path), dtype="float32", always_2d=True)
    samples = samples.mean(axis=1)  # downmix to mono
    if sr != SR:
        # Linear resample — fine for embeddings; use ffmpeg upstream for best quality.
        n = int(round(len(samples) * SR / sr))
        samples = np.interp(
            np.linspace(0, len(samples), n, endpoint=False),
            np.arange(len(samples)),
            samples,
        ).astype(np.float32)
    return samples


# ---- embedding -------------------------------------------------------------
def build_extractor(model: str) -> sherpa_onnx.SpeakerEmbeddingExtractor:
    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
        model=model, num_threads=NUM_THREADS, provider="cpu"
    )
    if not cfg.validate():
        sys.exit(f"Invalid model config for {model!r} — is the path right?")
    return sherpa_onnx.SpeakerEmbeddingExtractor(cfg)


def embed(extractor, samples: np.ndarray) -> np.ndarray:
    """One L2-normalized embedding for a whole clip."""
    stream = extractor.create_stream()
    stream.accept_waveform(SR, samples)
    stream.input_finished()
    vec = np.asarray(extractor.compute(stream), dtype=np.float32)
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))  # inputs are unit vectors


# ---- data ------------------------------------------------------------------
def _clips(root: Path) -> dict[str, list[Path]]:
    """{Name: [wavs]} from  root/<Name>/*.wav ."""
    out: dict[str, list[Path]] = {}
    if not root.is_dir():
        return out
    for person in sorted(p for p in root.iterdir() if p.is_dir()):
        wavs = sorted(person.glob("*.wav"))
        if wavs:
            out[person.name] = wavs
    return out


def enroll(extractor, enroll_dir: Path) -> dict[str, np.ndarray]:
    """One averaged, renormalized voiceprint per person."""
    prints: dict[str, np.ndarray] = {}
    for name, wavs in _clips(enroll_dir).items():
        vecs = [embed(extractor, load_wav(w)) for w in wavs]
        mean = np.mean(vecs, axis=0)
        norm = np.linalg.norm(mean)
        prints[name] = mean / norm if norm else mean
        print(f"  enrolled {name:<24} from {len(wavs)} clip(s)")
    return prints


# ---- reporting -------------------------------------------------------------
def pct(xs: list[float], p: float) -> float:
    return float(np.percentile(xs, p)) if xs else float("nan")


def main() -> None:
    if not MODEL:
        sys.exit("SPK_MODEL is unset — see the SETUP block at the top of this file.")
    print(f"model: {MODEL}")
    extractor = build_extractor(MODEL)
    print(f"embedding dim: {extractor.dim}\n")

    print("Enrolling known speakers:")
    prints = enroll(extractor, ENROLL_DIR)
    if len(prints) < 2:
        sys.exit(f"Need >=2 enrolled speakers in {ENROLL_DIR} — found {len(prints)}.")

    eval_clips = _clips(EVAL_DIR)
    if not eval_clips:
        sys.exit(f"No eval clips in {EVAL_DIR} — see the SETUP block.")

    rows = []          # (true, pred, top_cos, genuine_cos, impostor_cos)
    genuine, impostor = [], []
    print("\nScoring eval clips (true → predicted @ top cosine):")
    for true_name, wavs in eval_clips.items():
        for w in wavs:
            v = embed(extractor, load_wav(w))
            scores = {n: cosine(v, p) for n, p in prints.items()}
            pred = max(scores, key=scores.get)
            top = scores[pred]
            g = scores.get(true_name)  # None if the true speaker isn't enrolled
            imp = max((s for n, s in scores.items() if n != true_name), default=float("nan"))
            if g is not None:
                genuine.append(g)
                impostor.append(imp)
            mark = "✓" if pred == true_name else "✗"
            rows.append((true_name, pred, top, g, imp))
            print(f"  {mark} {true_name:<20} → {pred:<20} {top:+.3f}   ({w.name})")

    scored = [r for r in rows if r[3] is not None]  # true speaker was enrolled
    correct = sum(1 for t, p, *_ in scored if t == p)
    print(f"\nTop-1 accuracy (true speaker enrolled): {correct}/{len(scored)} "
          f"= {correct / len(scored):.1%}" if scored else "\nNo scorable clips.")

    if genuine and impostor:
        print("\nSeparation — the gap a threshold lives in:")
        print(f"  genuine  (same speaker):  min {min(genuine):.3f}  "
              f"p10 {pct(genuine,10):.3f}  median {pct(genuine,50):.3f}")
        print(f"  impostor (other speaker): max {max(impostor):.3f}  "
              f"p90 {pct(impostor,90):.3f}  median {pct(impostor,50):.3f}")

        print("\nThreshold sweep (accept top match only if top cosine >= t):")
        print("     t   accept%   acc@accept   impostor-accept%")
        for t in [round(x, 2) for x in np.arange(0.30, 0.71, 0.05)]:
            accepted = [r for r in scored if r[2] >= t]
            acc = (sum(1 for r in accepted if r[0] == r[1]) / len(accepted)) if accepted else float("nan")
            imp_acc = [i for i in impostor if i >= t]
            print(f"  {t:.2f}   {len(accepted)/len(scored):5.0%}     "
                  f"{acc:6.1%}        {len(imp_acc)/len(impostor):5.0%}")
        print("\n=> Pick a BAND: accept >= t_hi as the name; below t_lo fall back to the "
              "diarization label; in between, keep the label and let the LLM pass decide.")


if __name__ == "__main__":
    main()
