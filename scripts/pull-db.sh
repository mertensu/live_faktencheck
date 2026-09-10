#!/bin/bash
# Pull a snapshot of the production database for local development.
#
# Without this, backend/data/ is empty and the frontend shows nothing — there is
# no seed data in the repo, so a fresh clone has no fact-checks to render.
#
# Reads from the Cloudflare R2 backup bucket that Litestream replicates to, using
# the read-only token. No SSH access to the VPS is required, so every contributor
# can run it. It is the same restore path the production recovery procedure uses,
# which means routine use here keeps that path exercised.
#
# Requires the four R2_* variables in .env — see .env.example.
#
# Usage:
#   ./scripts/pull-db.sh                       # latest state
#   ./scripts/pull-db.sh 2026-09-08T21:00:00Z  # point in time (last 24h, see below)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_DB="$ROOT/backend/data/factcheck.db"

if ! command -v litestream >/dev/null 2>&1; then
    cat >&2 <<'EOF'
litestream is not installed.

  macOS:  brew install benbjohnson/litestream/litestream
  Linux:  see https://github.com/benbjohnson/litestream/releases

It is the same tool that replicates the production database, so restoring with it
is what makes this snapshot trustworthy.
EOF
    exit 1
fi

if [ ! -f "$ROOT/.env" ]; then
    echo "No .env found. Copy .env.example to .env and fill in the R2_* values." >&2
    exit 1
fi

# Read only the R2_* keys rather than sourcing .env, so a stray line in the file
# cannot execute anything here.
eval "$(grep -E '^R2_(ACCOUNT_ID|BUCKET|ACCESS_KEY_ID|SECRET_ACCESS_KEY)=' "$ROOT/.env" | sed 's/^/export /')"

MISSING=""
for var in R2_ACCOUNT_ID R2_BUCKET R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY; do
    [ -n "${!var:-}" ] || MISSING="$MISSING $var"
done
if [ -n "$MISSING" ]; then
    echo "Missing in .env:$MISSING" >&2
    echo "Ask for the read-only R2 token — see .env.example." >&2
    exit 1
fi

export LITESTREAM_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
export LITESTREAM_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
REPLICA_URL="s3://${R2_BUCKET}/factcheck?endpoint=${R2_ACCOUNT_ID}.r2.cloudflarestorage.com&region=auto"

# Restore into a temporary file first and only swap it in once it is verified, so a
# failed or interrupted download never leaves you without a working local database.
mkdir -p "$(dirname "$LOCAL_DB")"
TMP_DB="$LOCAL_DB.incoming.$$"
trap 'rm -f "$TMP_DB" "$TMP_DB"-shm "$TMP_DB"-wal' EXIT

# Point-in-time restores reach back as far as the retention configured on the
# server (24h of fine-grained history, 30 days of snapshots — see /etc/litestream.yml).
if [ $# -ge 1 ]; then
    echo "Restoring state as of $1"
    litestream restore -timestamp "$1" -o "$TMP_DB" "$REPLICA_URL"
else
    echo "Restoring latest state"
    litestream restore -o "$TMP_DB" "$REPLICA_URL"
fi

if command -v sqlite3 >/dev/null 2>&1; then
    INTEGRITY=$(sqlite3 "$TMP_DB" "PRAGMA integrity_check;" 2>&1)
    if [ "$INTEGRITY" != "ok" ]; then
        echo "Restored file failed its integrity check: $INTEGRITY" >&2
        echo "Your existing local database has been left untouched." >&2
        exit 1
    fi
fi

# Keep the previous local copy rather than overwriting it — a local DB may hold
# test sessions that are not on the server and exist nowhere else.
if [ -f "$LOCAL_DB" ]; then
    PREVIOUS="$LOCAL_DB.$(date +%Y%m%d-%H%M%S).bak"
    mv "$LOCAL_DB" "$PREVIOUS"
    rm -f "$LOCAL_DB"-shm "$LOCAL_DB"-wal
    echo "Existing local DB moved to $(basename "$PREVIOUS")"
fi

mv "$TMP_DB" "$LOCAL_DB"

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
