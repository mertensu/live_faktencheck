#!/bin/bash

# Production Stop Script
# Stops all processes and optionally commits fact-check data

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

echo -e "\n${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}🛑 Stopping Production Processes${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}\n"

# Stop Cloudflare Tunnel
if [ -f .cloudflared_pid ]; then
    TUNNEL_PID=$(cat .cloudflared_pid)
    if kill -0 $TUNNEL_PID 2>/dev/null; then
        kill $TUNNEL_PID 2>/dev/null || true
        print_success "Cloudflare Tunnel stopped (PID: $TUNNEL_PID)"
    else
        print_warning "Cloudflare Tunnel process not found"
    fi
    rm -f .cloudflared_pid
    rm -f .cloudflared_tunnel.log
else
    if pgrep -f "cloudflared.*tunnel" > /dev/null; then
        pkill -f "cloudflared.*tunnel" || true
        print_success "Cloudflare Tunnel stopped"
    else
        print_info "Cloudflare Tunnel not running"
    fi
fi

# Stop Backend
if [ -f .backend_pid ]; then
    BACKEND_PID=$(cat .backend_pid)
    if kill -0 $BACKEND_PID 2>/dev/null; then
        kill $BACKEND_PID 2>/dev/null || true
        print_success "Backend stopped (PID: $BACKEND_PID)"
    else
        print_warning "Backend process not found"
    fi
    rm -f .backend_pid
else
    if pgrep -f "python.*backend.app" > /dev/null; then
        pkill -f "python.*backend.app" || true
        print_success "Backend stopped"
    else
        print_info "Backend not running"
    fi
fi

# Stop Dev Frontend
if [ -f .frontend_pid ]; then
    FRONTEND_PID=$(cat .frontend_pid)
    if kill -0 $FRONTEND_PID 2>/dev/null; then
        kill $FRONTEND_PID 2>/dev/null || true
        print_success "Dev frontend stopped (PID: $FRONTEND_PID)"
    else
        print_warning "Dev frontend process not found"
    fi
    rm -f .frontend_pid
else
    if pgrep -f "vite.*dev" > /dev/null || lsof -ti:3000 > /dev/null 2>&1; then
        lsof -ti:3000 | xargs kill -9 2>/dev/null || true
        pkill -f "vite.*dev" || true
        print_success "Dev frontend stopped"
    else
        print_info "Dev frontend not running"
    fi
fi

# Ask about committing fact-checks (IMPORTANT for production workflow)
DATA_DIR="frontend/public/data"
if [ -d "$DATA_DIR" ] && [ -n "$(ls -A $DATA_DIR/*.json 2>/dev/null)" ]; then
    echo ""
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo -e "${BLUE}📊 Fact-Check Data${NC}"
    echo -e "${BLUE}════════════════════════════════════════${NC}"
    echo ""
    print_info "Found fact-check JSON files:"
    for file in $DATA_DIR/*.json; do
        if [ -f "$file" ]; then
            episode=$(basename "$file" .json)
            count=$(python3 -c "import json; data=json.load(open('$file')); print(len(data))" 2>/dev/null || echo "?")
            echo "   - $episode: $count fact-checks"
        fi
    done

    echo ""
    echo -e "${YELLOW}Note: Committing makes fact-checks permanent on GitHub Pages.${NC}"
    echo -e "${YELLOW}      For testing, you probably want to skip this.${NC}"
    echo ""
    read -p "Do you want to commit and push fact-check JSON files? (y/n): " -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[JjYy]$ ]]; then
        print_info "Adding JSON files to git..."
        git add $DATA_DIR/*.json

        if git diff --staged --quiet; then
            print_warning "No changes to commit."
        else
            EPISODE_KEYS=$(ls $DATA_DIR/*.json 2>/dev/null | xargs -n1 basename | sed 's/.json$//' | tr '\n' ',' | sed 's/,$//')
            COMMIT_MSG="Update fact checks: $EPISODE_KEYS"

            print_info "Committing: $COMMIT_MSG"
            git commit -m "$COMMIT_MSG"

            echo ""
            read -p "Do you want to push to GitHub? (y/n): " -n 1 -r
            echo ""

            if [[ $REPLY =~ ^[JjYy]$ ]]; then
                print_info "Pushing to GitHub..."
                git push
                print_success "Fact-checks pushed to GitHub!"
                print_info "Files are now available on GitHub Pages (even when backend is offline)."
            else
                print_info "Not pushed. You can push later with 'git push'."
            fi
        fi
    else
        print_info "Fact-checks not committed."
        print_info "Data remains in: $DATA_DIR/"
        print_info "You can commit later manually if needed."
    fi
fi

echo ""
print_success "All processes stopped!"
echo ""
