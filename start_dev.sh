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

EPISODE_KEY="test"
AUTOPILOT=false
BACKEND_PORT=5000
FRONTEND_DIR="frontend"

for arg in "$@"; do
    if [ "$arg" = "--autopilot" ]; then
        AUTOPILOT=true
    elif [[ "$arg" == --* ]]; then
        echo "Unknown option: $arg"
        exit 1
    else
        EPISODE_KEY="$arg"
    fi
done

print_header() {
    echo -e "\n${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}\n"
}

print_success() { echo -e "${GREEN}✅ $1${NC}"; }
print_error()   { echo -e "${RED}❌ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
print_info()    { echo -e "${BLUE}ℹ️  $1${NC}"; }

if [ "$EPISODE_KEY" = "test" ]; then
    print_info "Using generic 'test' config. Pass a real episode key to inherit its speakers."
    rm -f .test_override.json
else
    print_info "Copying config from '$EPISODE_KEY' → 'test' episode..."
    uv run python -c "
import json, sys
sys.path.insert(0, '.')
from config import SHOW_CONFIG
key = '$EPISODE_KEY'
if key not in SHOW_CONFIG:
    print(f'Unknown episode key: {key}')
    sys.exit(1)
cfg = dict(SHOW_CONFIG[key])
cfg.pop('publish', None)
with open('.test_override.json', 'w') as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
print(f'  guests: {cfg.get(\"guests\", [])}')
" || { print_error "Could not copy config for '$EPISODE_KEY'"; exit 1; }
    print_success "Test config set from '$EPISODE_KEY'"
fi

echo "$EPISODE_KEY" > .current_episode

print_header "🛠️  Dev Startup for: $EPISODE_KEY"

if [ -f .env ]; then
    set -a; source .env; set +a
    print_success "Loaded .env file"
else
    print_warning "No .env file found. Make sure API keys are set!"
fi

if [ "$AUTOPILOT" = "true" ]; then
    export AUTO_APPROVE=true
    print_info "Autopilot mode enabled: claims will be auto-approved (no admin review)"
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

# Step 2: Set Episode
print_header "Step 2: Set Episode"

if curl -s -X POST http://localhost:$BACKEND_PORT/api/set-episode \
    -H "Content-Type: application/json" \
    -d "{\"episode_key\": \"$EPISODE_KEY\"}" > /dev/null 2>&1; then
    print_success "Episode set: $EPISODE_KEY"
else
    print_warning "Could not set episode"
fi

# Step 3: Start Dev Frontend
print_header "Step 3: Start Dev Frontend"

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
echo -e "   Autopilot: ${YELLOW}$AUTOPILOT${NC}"
echo -e "   Backend: ${GREEN}http://localhost:$BACKEND_PORT${NC}"
echo -e "   Admin UI: ${GREEN}http://localhost:3000${NC}"
echo ""
echo -e "${BLUE}📝 Next Steps:${NC}"
echo -e "   1. Open Admin UI: ${YELLOW}http://localhost:3000${NC}"
echo -e "   2. Start Listener: ${YELLOW}uv run python listener.py $EPISODE_KEY${NC}"
echo ""
echo -e "${BLUE}🛑 Stop:${NC}"
echo -e "   ${YELLOW}./stop_production.sh${NC}"
echo ""
