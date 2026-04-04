#!/bin/bash
# manage_claim.sh — List and delete fact-check claims by ID.
#
# Usage:
#   ./manage_claim.sh <episode-key>              # list, then prompt to delete
#   ./manage_claim.sh <episode-key> list         # list only
#   ./manage_claim.sh <episode-key> delete <id>  # delete directly

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

EPISODE_KEY="${1:-}"
SUBCOMMAND="${2:-}"
CLAIM_ID="${3:-}"
BACKEND_PORT=5000
DB_PATH="backend/data/factcheck.db"

if [ -z "$EPISODE_KEY" ]; then
    echo "Usage: ./manage_claim.sh <episode-key> [list|delete <id>]"
    exit 1
fi

list_claims() {
    echo ""
    echo -e "${BLUE}Claims for episode: ${YELLOW}$EPISODE_KEY${NC}"
    echo ""
    uv run python -c "
import sqlite3, sys

db = sqlite3.connect('$DB_PATH')
rows = db.execute(
    'SELECT id, sprecher, behauptung, consistency, status FROM fact_checks WHERE episode_key=? ORDER BY id',
    ('$EPISODE_KEY',)
).fetchall()

if not rows:
    print('  No claims found for this episode.')
    sys.exit(0)

print(f'  {\"ID\":>4}  {\"Speaker\":<22} {\"Claim\":<55} {\"Rating\":<16} Status')
print(f'  {\"----\":>4}  {\"-\"*22} {\"-\"*55} {\"-\"*16} ------')
for r in rows:
    claim = (r[2][:52] + '...') if len(r[2]) > 55 else r[2]
    status = r[4] if r[4] else 'ok'
    print(f'  {r[0]:>4}  {r[1]:<22} {claim:<55} {r[3]:<16} {status}')
print()
db.close()
"
}

delete_claim() {
    local id="$1"
    echo -e "${BLUE}Deleting claim ID $id...${NC}"

    # Requires backend to be running
    response=$(curl -s -w "\n%{http_code}" -X DELETE "http://localhost:$BACKEND_PORT/api/fact-checks/$id")
    http_code=$(echo "$response" | tail -n1)
    body=$(echo "$response" | head -n-1)

    if [ "$http_code" = "200" ]; then
        echo -e "${GREEN}✅ Claim $id deleted.${NC}"
        echo -e "${BLUE}Re-exporting episode JSON...${NC}"
        uv run python export_episode.py --json "$EPISODE_KEY"
        echo -e "${GREEN}✅ JSON updated. Don't forget to commit and push.${NC}"
    elif [ "$http_code" = "404" ]; then
        echo -e "${RED}❌ Claim $id not found.${NC}"
        exit 1
    else
        echo -e "${RED}❌ Error ($http_code): $body${NC}"
        echo -e "${YELLOW}Is the backend running? Start with: ./start_dev.sh $EPISODE_KEY${NC}"
        exit 1
    fi
}

# ---- Main ----

list_claims

if [ "$SUBCOMMAND" = "list" ]; then
    exit 0
fi

if [ "$SUBCOMMAND" = "delete" ]; then
    if [ -z "$CLAIM_ID" ]; then
        echo -e "${RED}Error: delete requires a claim ID.${NC}"
        echo "Usage: ./manage_claim.sh $EPISODE_KEY delete <id>"
        exit 1
    fi
    delete_claim "$CLAIM_ID"
    exit 0
fi

# Interactive mode
printf "${BLUE}Delete claim ID (or q to quit): ${NC}"
read -r INPUT
if [ "$INPUT" = "q" ] || [ -z "$INPUT" ]; then
    echo "Exiting."
    exit 0
fi
delete_claim "$INPUT"
