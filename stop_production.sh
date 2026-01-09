#!/bin/bash

# Production Stop Script
# Stoppt alle gestarteten Prozesse (Cloudflare Tunnel, Backend)

set -e

# Farben
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
echo -e "${BLUE}🛑 Stoppe Production-Prozesse${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}\n"

# Stoppe Cloudflare Tunnel
if [ -f .cloudflared_pid ]; then
    TUNNEL_PID=$(cat .cloudflared_pid)
    if kill -0 $TUNNEL_PID 2>/dev/null; then
        kill $TUNNEL_PID 2>/dev/null || true
        print_success "Cloudflare Tunnel gestoppt (PID: $TUNNEL_PID)"
    else
        print_warning "Cloudflare Tunnel Prozess nicht gefunden"
    fi
    rm -f .cloudflared_pid
    rm -f .cloudflared_tunnel.log
else
    # Fallback: Suche nach cloudflared Tunnel Prozess
    if pgrep -f "cloudflared.*tunnel" > /dev/null; then
        pkill -f "cloudflared.*tunnel" || true
        print_success "Cloudflare Tunnel gestoppt"
    else
        print_info "Cloudflare Tunnel läuft nicht"
    fi
fi

# Stoppe Backend
if [ -f .backend_pid ]; then
    BACKEND_PID=$(cat .backend_pid)
    if kill -0 $BACKEND_PID 2>/dev/null; then
        kill $BACKEND_PID 2>/dev/null || true
        print_success "Backend gestoppt (PID: $BACKEND_PID)"
    else
        print_warning "Backend Prozess nicht gefunden"
    fi
    rm -f .backend_pid
else
    # Fallback: Suche nach Backend Prozess
    if pgrep -f "python.*backend/app.py" > /dev/null; then
        pkill -f "python.*backend/app.py" || true
        print_success "Backend gestoppt"
    else
        print_info "Backend läuft nicht"
    fi
fi

# Stoppe Dev-Frontend
if [ -f .frontend_pid ]; then
    FRONTEND_PID=$(cat .frontend_pid)
    if kill -0 $FRONTEND_PID 2>/dev/null; then
        kill $FRONTEND_PID 2>/dev/null || true
        print_success "Dev-Frontend gestoppt (PID: $FRONTEND_PID)"
    else
        print_warning "Dev-Frontend Prozess nicht gefunden"
    fi
    rm -f .frontend_pid
else
    # Fallback: Suche nach Vite/Dev-Server Prozess
    if pgrep -f "vite.*dev" > /dev/null || lsof -ti:3000 > /dev/null 2>&1; then
        lsof -ti:3000 | xargs kill -9 2>/dev/null || true
        pkill -f "vite.*dev" || true
        print_success "Dev-Frontend gestoppt"
    else
        print_info "Dev-Frontend läuft nicht"
    fi
fi

# Frage ob Fact-Checks committed werden sollen
DATA_DIR="frontend/public/data"
if [ -d "$DATA_DIR" ] && [ -n "$(ls -A $DATA_DIR/*.json 2>/dev/null)" ]; then
    echo ""
    print_info "Gefundene Fact-Check JSON-Dateien:"
    for file in $DATA_DIR/*.json; do
        if [ -f "$file" ]; then
            episode=$(basename "$file" .json)
            count=$(python3 -c "import json; data=json.load(open('$file')); print(len(data))" 2>/dev/null || echo "?")
            echo "   - $episode: $count Fact-Checks"
        fi
    done
    
    echo ""
    read -p "Möchtest du die Fact-Check JSON-Dateien committen und pushen? (j/n): " -n 1 -r
    echo ""
    
    if [[ $REPLY =~ ^[JjYy]$ ]]; then
        print_info "Füge JSON-Dateien zu Git hinzu..."
        git add $DATA_DIR/*.json
        
        if git diff --staged --quiet; then
            print_warning "Keine Änderungen zum Committen."
        else
            EPISODE_KEYS=$(ls $DATA_DIR/*.json 2>/dev/null | xargs -n1 basename | sed 's/.json$//' | tr '\n' ',' | sed 's/,$//')
            COMMIT_MSG="Update fact checks: $EPISODE_KEYS"
            
            print_info "Committte mit Nachricht: $COMMIT_MSG"
            git commit -m "$COMMIT_MSG"
            
            echo ""
            read -p "Möchtest du die Änderungen pushen? (j/n): " -n 1 -r
            echo ""
            
            if [[ $REPLY =~ ^[JjYy]$ ]]; then
                print_info "Pushe zu GitHub..."
                git push
                print_success "Fact-Checks wurden zu GitHub gepusht!"
                print_info "Die Dateien sind jetzt auf GitHub Pages verfügbar (auch wenn Backend offline ist)."
            else
                print_info "Nicht gepusht. Du kannst später mit 'git push' pushen."
            fi
        fi
    else
        print_info "Fact-Checks nicht committed. Du kannst später mit './commit_fact_checks.sh' committen."
    fi
fi

echo ""
print_success "Alle Prozesse gestoppt!"
