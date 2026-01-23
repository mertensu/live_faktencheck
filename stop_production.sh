#!/bin/bash

# Production Stop Script
# Stops all running processes (tunnel, backend, frontend)

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
    if pgrep -f "cloudflared.*tunnel.*run" > /dev/null; then
        pkill -f "cloudflared.*tunnel.*run" || true
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

# Cleanup log files
rm -f backend.log frontend_dev.log .cloudflared_tunnel.log 2>/dev/null

echo ""
print_success "All processes stopped!"
echo ""
