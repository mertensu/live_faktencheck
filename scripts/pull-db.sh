#!/bin/bash
# Pull a snapshot of the production database for local development.
#
# Without this, backend/data/ is empty and the frontend shows nothing — there is
# no seed data in the repo, so a fresh clone has no fact-checks to render.
#
# INTERIM VERSION: goes over SSH, so it only works for whoever holds a key to the
# VPS. Phase 2 of docs/team-setup-plan.md replaces the transfer below with a read
# from the R2 backup bucket, which every team member can use. Nothing else about
# the script changes.
#
# Usage:
#   ./scripts/pull-db.sh              # newest nightly backup
#   ./scripts/pull-db.sh 2026-09-08   # a specific day
set -euo pipefail

VPS=hostinger
REMOTE_DATA=/opt/fact_check/backend/data
LOCAL_DB="$(cd "$(dirname "$0")/.." && pwd)/backend/data/factcheck.db"

# Always fetch a `backup-*.db` snapshot, never factcheck.db itself: the live file
# is being written to, and a copy taken mid-write can arrive torn.
if [ $# -ge 1 ]; then
    REMOTE_FILE="$REMOTE_DATA/backup-$1.db"
    echo "Requested snapshot: backup-$1.db"
else
    echo "Looking up the newest snapshot on $VPS ..."
    REMOTE_FILE=$(ssh "$VPS" "ls -t $REMOTE_DATA/backup-*.db 2>/dev/null | head -1")
    if [ -z "$REMOTE_FILE" ]; then
        echo "No backup-*.db found in $REMOTE_DATA on $VPS." >&2
        echo "Check the nightly backup cron — see docs/deployment.md." >&2
        exit 1
    fi
    echo "Newest snapshot: $(basename "$REMOTE_FILE")"
fi

# Keep the previous local copy rather than overwriting it — a local DB may hold
# test sessions that are not on the server and exist nowhere else.
if [ -f "$LOCAL_DB" ]; then
    PREVIOUS="$LOCAL_DB.$(date +%Y%m%d-%H%M%S).bak"
    mv "$LOCAL_DB" "$PREVIOUS"
    echo "Existing local DB moved to $(basename "$PREVIOUS")"
fi

mkdir -p "$(dirname "$LOCAL_DB")"
scp "$VPS:$REMOTE_FILE" "$LOCAL_DB"

# Confirm the file is a readable SQLite DB and not, say, a truncated transfer.
if command -v sqlite3 >/dev/null 2>&1; then
    ROWS=$(sqlite3 "$LOCAL_DB" "SELECT COUNT(*) FROM fact_checks;")
    SESSIONS=$(sqlite3 "$LOCAL_DB" "SELECT COUNT(*) FROM sessions;")
    echo
    echo "Snapshot ready: $ROWS fact-checks, $SESSIONS sessions."
else
    echo
    echo "Snapshot ready (install sqlite3 to have this script verify its contents)."
fi

echo "Start the app with:  ./start_dev.sh <episode-key>"
