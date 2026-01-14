#!/bin/bash
# Start the Flask backend server

# Change to project root directory
cd "$(dirname "$0")/.."

# Load environment variables
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    echo "✅ Loaded .env file"
else
    echo "⚠️  No .env file found. Make sure API keys are set."
fi

# Start the backend
echo "🚀 Starting Fact-Check Backend..."
uv run python -m backend.app
