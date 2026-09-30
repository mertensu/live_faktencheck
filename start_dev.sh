#!/bin/bash

# Development Startup Script for Live Fact-Check
# Same as production but without Cloudflare Tunnel — results stay local only.

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

EPISODE_KEY=""
BACKEND_PORT=5000
FRONTEND_DIR="frontend"

for arg in "$@"; do
    if [[ "$arg" == --* ]]; then
        echo "Unknown option: $arg"
        exit 1
    else
        EPISODE_KEY="$arg"
    fi
done

if [ -z "$EPISODE_KEY" ]; then
    echo "Error: episode key required."
    echo "Usage: ./start_dev.sh <episode_key>"
    echo "Example: ./start_dev.sh maischberger-2026-01-28"
    exit 1
fi

print_header() {
    echo -e "\n${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}\n"
}

print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_error()   { echo -e "${RED}❌ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
print_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }

uv run python -c "
import sys
from backend.config import EPISODES
key = '$EPISODE_KEY'
if key not in EPISODES:
    print(f'Unknown episode key: {key}', file=sys.stderr)
    sys.exit(1)
ep = EPISODES[key]
print(f'  guests: {ep.guests}')
" || { print_error "Unknown episode key: '$EPISODE_KEY'"; exit 1; }

echo "$EPISODE_KEY" > .current_episode

print_header "🛠️  Dev Startup for: $EPISODE_KEY"

if [ -f .env ]; then
    set -a; source .env; set +a
    print_success "Loaded .env file"
else
    print_warning "No .env file found. Make sure API keys are set!"
fi

# Step 1: Start Backend
print_header "Step 1: Start Backend"

if pgrep -f "python.*backend.app" > /dev/null; then
    print_warning "Backend already running"
else
    print_info "Starting backend on port $BACKEND_PORT..."
    uv run python -m backend.app > backend.log 2>&1 &
    BACKEND_PID=$!
    echo $BACKEND_PID > .backend_pid
    sleep 3

    if curl -s http://localhost:$BACKEND_PORT/api/health > /dev/null 2>&1; then
        print_success "Backend started (PID: $BACKEND_PID)"
    else
        print_error "Backend could not start. Check backend.log"
        exit 1
    fi
fi

# Step 2: Start Dev Frontend
print_header "Step 2: Start Dev Frontend"

if pgrep -f "vite.*dev" > /dev/null || lsof -ti:3000 > /dev/null 2>&1; then
    print_warning "Dev frontend already running on port 3000"
else
    print_info "Starting dev frontend on port 3000..."
    cd "$FRONTEND_DIR" || exit 1

    if [ ! -d "node_modules" ]; then
        print_info "Installing dependencies..."
        bun install
    fi

    bun run dev > ../frontend_dev.log 2>&1 &
    FRONTEND_PID=$!
    echo $FRONTEND_PID > ../.frontend_pid
    cd ..
    sleep 3

    if curl -s http://localhost:3000 > /dev/null 2>&1; then
        print_success "Dev frontend started (PID: $FRONTEND_PID)"
    else
        print_warning "Dev frontend starting... (check frontend_dev.log)"
    fi
fi

# Summary
print_header "✅ Ready!"

echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}Dev Setup Successful — local only, nothing goes live${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}📋 Summary:${NC}"
echo -e "   Episode:   ${YELLOW}$EPISODE_KEY${NC}"
echo -e "   Backend:   ${GREEN}http://localhost:$BACKEND_PORT${NC}"
echo -e "   Session:   ${GREEN}http://localhost:3000/$EPISODE_KEY${NC}"
echo ""
echo -e "${BLUE}📝 Next Steps:${NC}"
echo -e "   1. Open ${YELLOW}http://localhost:3000/$EPISODE_KEY${NC} and unlock with an access code"
echo -e "   2. Click ${YELLOW}◉ Live-Check${NC} in the header to stream the mic"
echo ""
echo -e "${BLUE}🛑 Stop:${NC}"
echo -e "   ${YELLOW}Ctrl+C, or kill the backend/frontend processes (ports $BACKEND_PORT/3000)${NC}"
echo ""
