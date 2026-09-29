# Live Faktencheck

**Live at [live-faktencheck.de](https://live-faktencheck.de).**

Real-time fact-checking for German TV talk shows and other spoken-word formats. The app
listens along with a show, picks out verifiable claims sentence by sentence, and checks
them against authoritative German sources. Each result appears in the live transcript
within seconds.

## How It Works

```
  Audio stream (browser mic)
        │
        ▼
  Streaming transcription ─── live transcript, speaker labels
        │  sentence by sentence
        ▼
  Claim gate ─────────────── is this a verifiable, relevant factual claim?
        │
        ▼
  Reformulation (LLM) ────── self-contained claim + search queries
        │
        ▼
  Fast check ─────────────── parallel searches on trusted sources
        │                    → LLM: verdict + short reason + sources
        ▼
  Live transcript ────────── claim marked in place, result on click
```

## Design Principles

- **Speed over depth.** A check has to land while the topic is still on air, so there is
  no multi-step research loop: one round of parallel searches, one assessment.
- **Trusted sources only.** Searches are restricted to a curated list of official
  statistics offices, ministries, research institutes and established media
  ([`trusted_domains.py`](backend/services/trusted_domains.py), also shown at
  [/trusted-domains](https://live-faktencheck.de/trusted-domains)), ranked official-first.
  The model may only cite sources it actually found.
- **No guessed speakers.** Transcription only knows "speaker A, B, …". A human operator
  assigns names by click, because a claim attributed to the wrong person is worse than
  none.
- **Minimal data.** Only checked claims and their results are stored, not the transcript.
- **Neutrality.** The goal is to show how well a claim is backed by data, not to judge
  the person making it.

## Repository

```
backend/    FastAPI app — streaming session, claim gate, fast checker, SQLite
frontend/   React app — session wizard, live transcript, result cards
prompts/    LLM prompts (German)
docs/       deployment, configuration, development workflow
benchmarks/ offline A/B scripts for models and search settings
```

The system is German-first; LLM field descriptions live in `backend/lang.py`, see
[`docs/language-adaptation.md`](docs/language-adaptation.md) for other languages. Setup and
workflow for contributors: [`docs/development-workflow.md`](docs/development-workflow.md).

## Contributing

Any contributions are welcome — open an issue or pull request, or reach out at
[info@live-faktencheck.de](mailto:info@live-faktencheck.de).

## License

Source-available under [PolyForm Noncommercial 1.0.0](LICENSE). Noncommercial use is
permitted; for commercial use, please get in touch at
[info@live-faktencheck.de](mailto:info@live-faktencheck.de).
