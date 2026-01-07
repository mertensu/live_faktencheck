#!/bin/bash
# Backend Start-Script für uv
cd "$(dirname "$0")/.."
uv run python backend/app.py

