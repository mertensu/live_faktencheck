"""
Offline voiceprint enrollment: build the ``<Name>.npy`` store the live lane reads.

Reads reference clips at ``enroll/<Name>/*.wav`` (16 kHz mono), averages one embedding per
person with the same sherpa-onnx extractor the spike uses, and writes a unit-vector
``<Name>.npy`` per person into the voiceprint store. At runtime ``SpeakerIdentifier`` loads
these (filtered to the episode's guests) and argmaxes each utterance against them — see
``backend/services/speaker_id.py`` and ``docs/speaker-id-integration-plan.md`` (§5.3).

This is bench-only (opt-in ``--group bench``; uses ``soundfile`` to read WAVs). There is no
enrollment in the live path — enrollment happens here, ahead of the show.

──────────────────────────────────────────────────────────────────────────────
SETUP  (same deps + macOS dylib note as benchmarks/speaker_id_bench.py)

  uv sync --group bench                      # sherpa-onnx, numpy, soundfile
  # macOS only: link libonnxruntime.dylib (see speaker_id_bench.py header).

  Lay out reference clips (public speeches/interviews are fine; 15-60 s each):
    benchmarks/data/speaker_id/enroll/<Name>/*.wav     # or point SPK_ENROLL_DIR elsewhere
  Convert anything else:  ffmpeg -i in -ar 16000 -ac 1 out.wav

RUN
  SPK_MODEL=/path/to/model.onnx uv run --group bench python benchmarks/enroll_voiceprints.py
  # writes to backend/data/voiceprints/ by default; override with SPEAKER_ID_VOICEPRINTS_DIR
──────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
from pathlib import Path

import numpy as np

# Reuse the spike's proven extractor/WAV/enroll helpers — no duplication.
from speaker_id_bench import ENROLL_DIR, MODEL, build_extractor, enroll

OUT_DIR = Path(os.getenv("SPEAKER_ID_VOICEPRINTS_DIR", "backend/data/voiceprints"))


def main() -> None:
    if not MODEL:
        sys.exit("SPK_MODEL is unset — see the SETUP block at the top of this file.")
    print(f"model: {MODEL}")
    print(f"enroll dir: {ENROLL_DIR}")
    extractor = build_extractor(MODEL)

    prints = enroll(extractor, ENROLL_DIR)
    if not prints:
        sys.exit(f"No enrollment clips found under {ENROLL_DIR} — see the SETUP block.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, vec in prints.items():
        out = OUT_DIR / f"{name}.npy"
        np.save(out, np.asarray(vec, dtype=np.float32))
        print(f"  wrote {out}")
    print(f"\n{len(prints)} voiceprint(s) written to {OUT_DIR}")


if __name__ == "__main__":
    main()
