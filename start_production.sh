#!/bin/bash

# Production Startup Script for Live Fact-Check
# Starts: Cloudflare Tunnel (named), Backend, Frontend (dev mode for admin)

set -e  # Exit on errors

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
EPISODE_KEY="${1:-}"  # First parameter: Episode key (e.g., maischberger-2025-09-19)
BACKEND_PORT=5000
FRONTEND_DIR="frontend"
TUNNEL_NAME="faktencheck-api"
TUNNEL_LOG=".cloudflared_tunnel.log"

# Functions
print_header() {
    echo -e "\n${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}\n"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Check for episode key
if [ -z "$EPISODE_KEY" ]; then
    print_error "Episode key missing!"
    echo "Usage: ./start_production.sh <episode-key>"
    echo "Example: ./start_production.sh maischberger-2025-09-19"
    echo ""
    echo "Available episodes (from config.py):"
    uv run python -c "from config import get_all_episodes; print('  ' + '\n  '.join(get_all_episodes()))" 2>/dev/null || echo "  (Could not load config)"
    exit 1
fi

echo "$EPISODE_KEY" > .current_episode

print_header "🚀 Production Startup for: $EPISODE_KEY"

# Load .env file if exists
if [ -f .env ]; then
    set -a
    source .env
    set +a
    print_success "Loaded .env file"
else
    print_warning "No .env file found. Make sure API keys are set!"
fi

# Step 1: Check Cloudflare Tunnel
print_header "Step 1: Cloudflare Tunnel"

if ! command -v cloudflared &> /dev/null; then
    print_error "cloudflared not installed!"
    print_info "Install with: brew install cloudflared"
    exit 1
fi

# Check if config exists
if [ ! -f "$HOME/.cloudflared/config.yml" ]; then
    print_error "Cloudflare tunnel config not found!"
    print_info "Expected: ~/.cloudflared/config.yml"
    print_info "Run: cloudflared tunnel login && cloudflared tunnel create $TUNNEL_NAME"
    exit 1
fi

if ! pgrep -f "cloudflared.*tunnel.*run" > /dev/null; then
    print_info "Starting Cloudflare Tunnel ($TUNNEL_NAME)..."
    cloudflared tunnel run $TUNNEL_NAME > "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
    echo $TUNNEL_PID > .cloudflared_pid
    sleep 3

    if kill -0 $TUNNEL_PID 2>/dev/null; then
        print_success "Cloudflare Tunnel started (PID: $TUNNEL_PID)"
    else
        print_error "Cloudflare Tunnel failed to start. Check $TUNNEL_LOG"
        exit 1
    fi
else
    print_success "Cloudflare Tunnel already running"
fi

# Step 2: Start Backend
print_header "Step 2: Start Backend"

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

# Step 3: Verify tunnel connectivity
print_header "Step 3: Verify Tunnel"

print_info "Testing API via tunnel..."
sleep 2
if curl -s https://api.live-faktencheck.de/api/health > /dev/null 2>&1; then
    print_success "API accessible at https://api.live-faktencheck.de"
else
    print_warning "API not yet accessible via tunnel (may take a moment)"
    print_info "Test manually: curl https://api.live-faktencheck.de/api/health"
fi

# Step 4: Set episode in backend
print_header "Step 4: Set Episode"

if curl -s -X POST http://localhost:$BACKEND_PORT/api/set-episode \
    -H "Content-Type: application/json" \
    -d "{\"episode_key\": \"$EPISODE_KEY\"}" > /dev/null 2>&1; then
    print_success "Episode set: $EPISODE_KEY"
else
    print_warning "Could not set episode"
fi

# Step 5: Start Dev Frontend (for admin mode)
print_header "Step 5: Start Dev Frontend (Admin Mode)"

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
print_header "✅ Setup Complete!"

echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}Production Setup Successful!${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}📋 Summary:${NC}"
echo -e "   Episode: ${YELLOW}$EPISODE_KEY${NC}"
echo -e "   Backend API: ${GREEN}https://api.live-faktencheck.de${NC}"
echo -e "   Backend (local): ${GREEN}http://localhost:$BACKEND_PORT${NC}"
echo -e "   Admin UI: ${GREEN}http://localhost:3000${NC}"
echo -e "   Public UI: ${GREEN}https://live-faktencheck.de${NC}"
echo ""
echo -e "${BLUE}📝 Next Steps:${NC}"
echo -e "   1. Open Admin UI: ${YELLOW}http://localhost:3000${NC}"
echo -e "   2. Start Listener: ${YELLOW}uv run python listener.py $EPISODE_KEY${NC}"
echo ""
echo -e "${BLUE}🔄 Workflow:${NC}"
echo -e "   Audio → Backend (transcription + claim extraction) → Admin UI"
echo -e "   → Approve claims → Fact-checking → Live on Cloudflare Pages"
echo ""
echo -e "${BLUE}🛑 Stop:${NC}"
echo -e "   ${YELLOW}./stop_production.sh${NC}"
echo ""
