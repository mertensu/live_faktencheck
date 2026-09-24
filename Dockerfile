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
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

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
