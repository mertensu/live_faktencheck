# Contributing to Live Faktencheck

Thank you for your interest in contributing! This document provides guidelines for contributing to this project.

## Development Setup

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) for Python dependency management
- [bun](https://bun.sh/) for frontend dependency management
- `sqlite3` (optional, for inspecting the local database)

### Installation

Budget about 30 minutes. If anything here does not work as written, that is a bug
in this document — please open an issue.

1. Clone the repository:
   ```bash
   git clone https://github.com/mertensu/live_faktencheck.git
   cd live_faktencheck
   ```

2. Install Python dependencies (this includes ruff and the test tools):
   ```bash
   uv sync
   ```

3. Install frontend dependencies:
   ```bash
   cd frontend && bun install
   ```

4. Set up environment variables:
   ```bash
   cp .env.example .env
   ```
   `.env.example` documents every variable the code reads, including `ACCESS_CODES`:
   without it the app starts, but every cost-incurring endpoint rejects all requests.

   **You do not need API keys to start contributing.** The unit tests run without any
   — only the integration tests and the live pipeline call out to providers. When you
   do need keys, sign up for your **own** at [Google AI Studio](https://aistudio.google.com/),
   [Tavily](https://tavily.com/) and [AssemblyAI](https://www.assemblyai.com/); all three
   offer a free tier. Set a spending limit at each. Never use the production keys: a
   runaway local test must not be able to exhaust the live budget mid-broadcast.

5. Pull a database snapshot so the app has something to display:
   ```bash
   ./scripts/pull-db.sh
   ```
   `backend/data/` is empty in a fresh clone — no snapshot means an empty frontend.
   This step currently needs VPS access; see `docs/team-setup-plan.md` (Phase 2) for
   the R2-based replacement.

### Running the Development Servers

```bash
# Both together (preferred)
./start_dev.sh <episode-key>

# Or separately:
./backend/run.sh                  # backend on port 5000
cd frontend && bun run dev        # frontend on port 3000
```

## Running Tests

**Always use `uv run` for Python commands and `bun` for frontend commands.**

```bash
# Run unit tests (fast, no API calls)
uv run pytest backend/tests -m "not integration"

# Run a specific test
uv run pytest backend/tests -k "test_name"

# Run integration tests (requires API keys)
uv run pytest backend/tests -m integration
```

## Code Style

We use [ruff](https://github.com/astral-sh/ruff) for Python linting.

```bash
# Check for issues
uv run ruff check backend/

# Auto-fix issues
uv run ruff check --fix backend/
```

Please ensure your code passes linting before submitting a PR.

## Pull Request Process

1. **Fork the repository** and create your branch from `main`.

2. **Make your changes** following the code style guidelines.

3. **Run tests** to ensure nothing is broken:
   ```bash
   uv run pytest backend/tests -m "not integration"
   ```

4. **Run the linter** and fix any issues:
   ```bash
   uv run ruff check --fix backend/
   ```

5. **Build the frontend** if you made frontend changes:
   ```bash
   cd frontend && bun run build
   ```

6. **Commit your changes** with a clear, concise commit message.

7. **Open a Pull Request** with a description of your changes.

## Questions?

Feel free to open an issue if you have questions or need help getting started.
