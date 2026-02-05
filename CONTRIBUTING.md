# Contributing to Live Faktencheck

Thank you for your interest in contributing! This document provides guidelines for contributing to this project.

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- [uv](https://github.com/astral-sh/uv) for Python dependency management
- [bun](https://bun.sh/) for frontend dependency management

### Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/fact_check.git
   cd fact_check
   ```

2. Install Python dependencies:
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
   # Edit .env with your API keys
   ```

### Running the Development Servers

```bash
# Backend (port 5000)
./backend/run.sh

# Frontend (port 3000, in a separate terminal)
cd frontend && bun run dev
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
