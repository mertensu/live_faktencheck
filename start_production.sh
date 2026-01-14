#!/bin/bash

# Production Startup Script for Live Fact-Check
# Starts: Cloudflare Tunnel, Backend, Frontend (dev mode for admin)

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

print_header "🚀 Production Startup for: $EPISODE_KEY"

# Load .env file if exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
    print_success "Loaded .env file"
else
    print_warning "No .env file found. Make sure API keys are set!"
fi

# Step 1: Check Cloudflare Tunnel
print_header "Step 1: Cloudflare Tunnel"

if ! command -v cloudflared &> /dev/null; then
    print_error "cloudflared not installed!"
    print_info "Install with: brew install cloudflare/cloudflare/cloudflared"
    exit 1
fi

if ! pgrep -f "cloudflared.*tunnel" > /dev/null; then
    print_warning "Cloudflare Tunnel not running. Starting..."
    cloudflared tunnel --url http://localhost:$BACKEND_PORT > "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
    echo $TUNNEL_PID > .cloudflared_pid
    print_info "Waiting 5 seconds for Cloudflare Tunnel..."
    sleep 5
    print_success "Cloudflare Tunnel started (PID: $TUNNEL_PID)"
else
    print_success "Cloudflare Tunnel already running"
fi

# Step 2: Get Cloudflare Tunnel URL
print_header "Step 2: Extract Tunnel URL"

TUNNEL_URL=""
MAX_RETRIES=15
RETRY_COUNT=0

while [ -z "$TUNNEL_URL" ] && [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    sleep 1
    if [ -f "$TUNNEL_LOG" ]; then
        TUNNEL_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ -z "$TUNNEL_URL" ]; then
    print_error "Could not get Cloudflare Tunnel URL!"
    print_info "Check log: cat $TUNNEL_LOG"
    exit 1
fi

print_success "Tunnel URL: $TUNNEL_URL"

# Step 3: Update GitHub Secret and trigger deployment
print_header "Step 3: GitHub Secret & Deployment"

SECRET_UPDATED=false
if command -v gh &> /dev/null; then
    if gh auth status &>/dev/null; then
        print_info "Updating GitHub Secret..."
        if gh secret set VITE_BACKEND_URL --body "$TUNNEL_URL" 2>/dev/null; then
            print_success "GitHub Secret updated: $TUNNEL_URL"
            SECRET_UPDATED=true
            sleep 2

            # Auto-trigger deployment
            if gh workflow run "Deploy to GitHub Pages" 2>/dev/null; then
                print_success "Deployment triggered automatically!"
            else
                print_warning "Could not trigger deployment. Please trigger manually."
            fi
        else
            print_warning "Could not update GitHub Secret"
        fi
    else
        print_warning "GitHub CLI not authenticated. Run: gh auth login"
    fi
else
    print_warning "GitHub CLI not installed. Set secret manually:"
    print_info "   GitHub → Settings → Secrets → VITE_BACKEND_URL = $TUNNEL_URL"
fi

# Step 4: Build frontend locally
print_header "Step 4: Build Frontend (local)"

cd "$FRONTEND_DIR" || exit 1

if [ ! -d "node_modules" ]; then
    print_info "Installing npm dependencies..."
    npm install
fi

print_info "Building frontend with VITE_BACKEND_URL=$TUNNEL_URL..."
if VITE_BACKEND_URL="$TUNNEL_URL" npm run build; then
    print_success "Frontend built successfully"
else
    print_error "Frontend build failed!"
    exit 1
fi

cd ..

# Step 5: Start Backend
print_header "Step 5: Start Backend"

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

# Step 6: Set episode in backend
print_header "Step 6: Set Episode"

if curl -s -X POST http://localhost:$BACKEND_PORT/api/set-episode \
    -H "Content-Type: application/json" \
    -d "{\"episode_key\": \"$EPISODE_KEY\"}" > /dev/null 2>&1; then
    print_success "Episode set: $EPISODE_KEY"
else
    print_warning "Could not set episode"
fi

# Step 7: Start Dev Frontend (for admin mode)
print_header "Step 7: Start Dev Frontend (Admin Mode)"

if pgrep -f "vite.*dev" > /dev/null || lsof -ti:3000 > /dev/null 2>&1; then
    print_warning "Dev frontend already running on port 3000"
else
    print_info "Starting dev frontend on port 3000..."
    cd "$FRONTEND_DIR" || exit 1
    npm run dev > ../frontend_dev.log 2>&1 &
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
echo -e "   Tunnel URL: ${YELLOW}$TUNNEL_URL${NC}"
echo -e "   Backend: ${GREEN}http://localhost:$BACKEND_PORT${NC}"
echo -e "   Admin UI: ${GREEN}http://localhost:3000${NC}"
echo ""
echo -e "${BLUE}📝 Next Steps:${NC}"
echo -e "   1. Open Admin UI: ${YELLOW}http://localhost:3000${NC}"
echo -e "   2. Start Listener: ${YELLOW}uv run python listener.py $EPISODE_KEY${NC}"
echo ""
echo -e "${BLUE}🔄 Workflow:${NC}"
echo -e "   Audio → Backend (transcription + claim extraction) → Admin UI"
echo -e "   → Approve claims → Fact-checking → GitHub Pages"
echo ""
echo -e "${BLUE}🛑 Stop:${NC}"
echo -e "   ${YELLOW}./stop_production.sh${NC}"
echo ""
