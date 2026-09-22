# Speaker-ID benchmark data (git-ignored)

Drop audio here for `benchmarks/speaker_id_bench.py`. Nothing in this folder is committed
(see `.gitignore`) — it's your local voiceprints and episode slices, not repo content.

```
enroll/<Name>/*.wav   # reference clips per known speaker (public speeches/interviews to
                      #   start; 15–60 s each; more clips per person = steadier voiceprint)
eval/<Name>/*.wav     # held-out labelled utterances to score (e.g. slices of the recorded
                      #   Connemann/Dröge episode used in streaming tests)
```

All WAVs must be **16 kHz mono**. Convert anything else:

```sh
ffmpeg -i input.mp4 -ar 16000 -ac 1 -vn enroll/Connemann/bundestag_2025.wav
```

Use the exact same `<Name>` spelling under `enroll/` and `eval/` so the scorer can tell a
hit from a miss. A person can appear in `eval/` without being in `enroll/` — those clips
measure the "unknown speaker" case (should fall below the accept threshold).
