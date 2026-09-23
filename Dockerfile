# Backend runtime — the same environment locally, in CI and in production.
FROM python:3.12-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies in their own layer: they change rarely and stay cached across code edits.
# --extra speakerid pulls sherpa-onnx (voiceprint speaker ID for the live fast lane);
# the code path stays dark until SPEAKER_ID_ENABLED is set.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --extra speakerid

# Speaker-embedding model (CAM++, ~28 MB) for voiceprint speaker ID, baked in from the
# pinned k2-fsa release and checked by sha256 (keeps it out of git, reproducible build).
# Lives under /app/models, NOT under backend/data — the data bind mount would hide it.
# (The "recongition" typo is the real release tag.)
ARG SPEAKER_ID_MODEL_URL=https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx
ARG SPEAKER_ID_MODEL_SHA256=aa3cfc16963a10586a9393f5035d6d6b57e98d358b347f80c2a30bf4f00ceba2
ENV SPEAKER_ID_MODEL=/app/models/campplus.onnx
RUN python -c "import hashlib, os, urllib.request as u; \
data = u.urlopen(os.environ['SPEAKER_ID_MODEL_URL'], timeout=120).read(); \
digest = hashlib.sha256(data).hexdigest(); \
assert digest == os.environ['SPEAKER_ID_MODEL_SHA256'], 'speaker model sha256 mismatch: ' + digest; \
os.makedirs(os.path.dirname(os.environ['SPEAKER_ID_MODEL']), exist_ok=True); \
open(os.environ['SPEAKER_ID_MODEL'], 'wb').write(data)"

# pyproject.toml has no [build-system], so uv treats this as a virtual project: it
# installs the dependencies but not the code. The code is just copied in and imported
# from WORKDIR — a second `uv sync` after this COPY would do nothing.
COPY prompts/ ./prompts/
COPY backend/ ./backend/

# The SQLite DB does not belong in the image — mount it:
#   docker run -v "$PWD/backend/data:/app/backend/data" ...
VOLUME ["/app/backend/data"]

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health').read()"

# Single process required: backend/state.py holds the claim queue and pipeline status
# in memory. No --workers, no --reload, no second replica.
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "5000"]
