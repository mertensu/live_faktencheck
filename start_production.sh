#!/bin/bash

# Production Startup Script für Live Fact-Check
# Automatisiert: Cloudflare Tunnel, Frontend-Build, Backend-Start

set -e  # Beende bei Fehlern

# Farben für Output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Konfiguration
EPISODE_KEY="${1:-}"  # Erster Parameter: Episode-Key (z.B. maischberger-2025-09-19)
BACKEND_PORT=5000
FRONTEND_DIR="frontend"
TUNNEL_LOG=".cloudflared_tunnel.log"

# Funktionen
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

# Prüfe ob Episode-Key angegeben wurde
if [ -z "$EPISODE_KEY" ]; then
    print_error "Episode-Key fehlt!"
    echo "Verwendung: ./start_production.sh <episode-key>"
    echo "Beispiel: ./start_production.sh maischberger-2025-09-19"
    exit 1
fi

print_header "🚀 Production Startup für: $EPISODE_KEY"

# Schritt 1: Prüfe ob Cloudflare Tunnel läuft
print_header "Schritt 1: Cloudflare Tunnel prüfen"

if ! command -v cloudflared &> /dev/null; then
    print_error "cloudflared nicht installiert!"
    print_info "Installiere mit: brew install cloudflare/cloudflare/cloudflared"
    print_info "Oder: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/"
    exit 1
fi

if ! pgrep -f "cloudflared.*tunnel" > /dev/null; then
    print_warning "Cloudflare Tunnel läuft nicht. Starte Tunnel..."
    # Starte Cloudflare Tunnel im Hintergrund und logge Output
    cloudflared tunnel --url http://localhost:$BACKEND_PORT > "$TUNNEL_LOG" 2>&1 &
    TUNNEL_PID=$!
    echo $TUNNEL_PID > .cloudflared_pid
    print_info "Warte 5 Sekunden auf Cloudflare Tunnel..."
    sleep 5
    print_success "Cloudflare Tunnel gestartet (PID: $TUNNEL_PID)"
else
    print_success "Cloudflare Tunnel läuft bereits"
fi

# Schritt 2: Hole Cloudflare Tunnel URL
print_header "Schritt 2: Cloudflare Tunnel URL extrahieren"

TUNNEL_URL=""
MAX_RETRIES=15
RETRY_COUNT=0

# Cloudflare Tunnel gibt die URL in der Ausgabe aus, Format: "https://xxxxx.trycloudflare.com"
# Die URL erscheint in einer Zeile wie: "https://xxxxx.trycloudflare.com"
while [ -z "$TUNNEL_URL" ] && [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    sleep 1
    # Suche nach URL in der Log-Datei (verschiedene Patterns)
    if [ -f "$TUNNEL_LOG" ]; then
        # Pattern 1: Direkte URL in Zeile
        TUNNEL_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
        # Pattern 2: URL mit "https://" am Anfang der Zeile
        if [ -z "$TUNNEL_URL" ]; then
            TUNNEL_URL=$(grep -E '^https://' "$TUNNEL_LOG" 2>/dev/null | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | head -1)
        fi
        # Pattern 3: URL irgendwo in der Zeile
        if [ -z "$TUNNEL_URL" ]; then
            TUNNEL_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -1)
        fi
    fi
    RETRY_COUNT=$((RETRY_COUNT + 1))
done

if [ -z "$TUNNEL_URL" ]; then
    print_error "Konnte Cloudflare Tunnel URL nicht ermitteln!"
    print_info "Bitte manuell prüfen:"
    if [ -f "$TUNNEL_LOG" ]; then
        print_info "  Log-Datei: cat $TUNNEL_LOG"
        print_info "  Letzte Zeilen:"
        tail -10 "$TUNNEL_LOG" | head -5
    fi
    print_info "  Oder starte manuell: cloudflared tunnel --url http://localhost:$BACKEND_PORT"
    print_info "  Die URL wird direkt in der Ausgabe angezeigt."
    exit 1
fi

print_success "Cloudflare Tunnel URL: $TUNNEL_URL"

# Schritt 3: GitHub Secret aktualisieren und Deployment auslösen
print_header "Schritt 3: GitHub Secret aktualisieren und Deployment"

print_info "Hinweis: Das GitHub Secret wird für GitHub Actions Builds verwendet."
print_info "Nach dem Secret-Update muss das Deployment manuell ausgelöst werden."

SECRET_UPDATED=false
if command -v gh &> /dev/null; then
    print_info "GitHub CLI gefunden. Prüfe Authentifizierung..."
    if gh auth status &>/dev/null; then
        print_info "GitHub CLI authentifiziert. Aktualisiere Secret..."
        if gh secret set VITE_BACKEND_URL --body "$TUNNEL_URL" 2>/dev/null; then
            print_success "GitHub Secret aktualisiert: $TUNNEL_URL"
            SECRET_UPDATED=true
            # Warte kurz, damit GitHub das Secret vollständig aktualisiert hat
            print_info "Warte 2 Sekunden, damit GitHub das Secret vollständig aktualisiert..."
            sleep 2
        else
            print_warning "Konnte GitHub Secret nicht aktualisieren (möglicherweise keine Berechtigung)"
            print_info "Bitte manuell setzen: GitHub → Settings → Secrets → VITE_BACKEND_URL = $TUNNEL_URL"
        fi
    else
        print_warning "GitHub CLI nicht authentifiziert. Führe aus: gh auth login"
        print_info "Bitte manuell setzen: GitHub → Settings → Secrets → VITE_BACKEND_URL = $TUNNEL_URL"
    fi
else
    print_warning "GitHub CLI nicht installiert. Überspringe automatisches Update."
    print_info "Bitte manuell setzen: GitHub → Settings → Secrets → VITE_BACKEND_URL = $TUNNEL_URL"
fi

# Deployment auslösen (automatisch wenn Secret aktualisiert wurde, sonst fragen)
echo ""
if command -v gh &> /dev/null && gh auth status &>/dev/null; then
    if [ "$SECRET_UPDATED" = true ]; then
        # Secret wurde aktualisiert → Deployment automatisch auslösen
        print_info "Secret wurde aktualisiert. Löse Deployment automatisch aus..."
        # Zusätzliche kurze Verzögerung, damit GitHub Actions das Secret sicher lesen kann
        sleep 1
        if gh workflow run "Deploy to GitHub Pages" 2>/dev/null; then
            print_success "✅ Deployment automatisch ausgelöst!"
            print_info "   Workflow läuft jetzt auf GitHub und baut mit der neuen URL."
            print_info "   Prüfe Status: gh run list"
            print_info "   Oder: https://github.com/mertensu/live_faktencheck/actions"
        else
            print_warning "Konnte Workflow nicht automatisch auslösen. Bitte manuell:"
            print_info "   GitHub → Actions → 'Deploy to GitHub Pages' → Run workflow"
        fi
    else
        # Secret wurde nicht aktualisiert → Frage ob Deployment ausgelöst werden soll
        print_warning "Secret wurde nicht aktualisiert. Möglicherweise verwendet GitHub Pages noch die alte URL."
        read -p "Möchtest du das GitHub Pages Deployment trotzdem auslösen? (j/n): " -n 1 -r
        echo ""
        if [[ $REPLY =~ ^[JjYy]$ ]]; then
            print_info "Löse GitHub Actions Workflow aus..."
            if gh workflow run "Deploy to GitHub Pages" 2>/dev/null; then
                print_success "Deployment ausgelöst! Prüfe Status: gh run list"
                print_info "Workflow läuft jetzt auf GitHub und baut mit dem Secret."
            else
                print_warning "Konnte Workflow nicht auslösen. Bitte manuell:"
                print_info "   GitHub → Actions → 'Deploy to GitHub Pages' → Run workflow"
            fi
        else
            print_info "Deployment übersprungen. Du kannst es später manuell auslösen:"
            print_info "   GitHub → Actions → 'Deploy to GitHub Pages' → Run workflow"
        fi
    fi
else
    print_warning "⚠️  WICHTIG: GitHub CLI nicht verfügbar/authentifiziert"
    print_info "Das GitHub Secret wurde NICHT automatisch aktualisiert!"
    print_info "Bitte manuell:"
    print_info "   1. GitHub → Settings → Secrets → VITE_BACKEND_URL = $TUNNEL_URL"
    print_info "   2. GitHub → Actions → 'Deploy to GitHub Pages' → Run workflow"
fi

# Schritt 4: Frontend bauen (lokal mit Environment Variable)
print_header "Schritt 4: Frontend bauen (lokal)"

cd "$FRONTEND_DIR" || exit 1

print_info "Baue Frontend lokal mit VITE_BACKEND_URL=$TUNNEL_URL..."
print_info "   (Dieser Build ist für lokale Tests. Für GitHub Pages siehe Schritt 8)"

if VITE_BACKEND_URL="$TUNNEL_URL" npm run build; then
    print_success "Frontend erfolgreich gebaut (lokal)"
    print_info "   Build-Ordner: dist/ (wird nicht zu GitHub Pages deployed)"
else
    print_error "Frontend-Build fehlgeschlagen!"
    exit 1
fi

cd ..

# Schritt 5: Backend starten (im Hintergrund)
print_header "Schritt 5: Backend starten"

if pgrep -f "python.*backend/app.py" > /dev/null; then
    print_warning "Backend läuft bereits"
else
    print_info "Starte Backend auf Port $BACKEND_PORT..."
    # Starte Backend im Hintergrund
    uv run python backend/app.py > backend.log 2>&1 &
    BACKEND_PID=$!
    echo $BACKEND_PID > .backend_pid
    sleep 2
    
    # Prüfe ob Backend läuft
    if curl -s http://localhost:$BACKEND_PORT/api/health > /dev/null 2>&1; then
        print_success "Backend gestartet (PID: $BACKEND_PID)"
    else
        print_error "Backend konnte nicht gestartet werden. Prüfe backend.log"
        exit 1
    fi
fi

# Schritt 6: Episode im Backend setzen
print_header "Schritt 6: Episode im Backend setzen"

if curl -s -X POST http://localhost:$BACKEND_PORT/api/set-episode \
    -H "Content-Type: application/json" \
    -d "{\"episode_key\": \"$EPISODE_KEY\"}" > /dev/null 2>&1; then
    print_success "Episode im Backend gesetzt: $EPISODE_KEY"
else
    print_warning "Konnte Episode nicht im Backend setzen"
fi

# Schritt 7: Dev-Frontend starten (für Admin-Modus)
print_header "Schritt 7: Dev-Frontend starten (Admin-Modus)"

if pgrep -f "vite.*dev" > /dev/null || lsof -ti:3000 > /dev/null 2>&1; then
    print_warning "Dev-Frontend läuft bereits auf Port 3000"
else
    print_info "Starte Dev-Frontend auf Port 3000..."
    cd "$FRONTEND_DIR" || exit 1
    npm run dev > ../frontend_dev.log 2>&1 &
    FRONTEND_PID=$!
    echo $FRONTEND_PID > ../.frontend_pid
    cd ..
    sleep 3
    
    # Prüfe ob Dev-Frontend läuft
    if curl -s http://localhost:3000 > /dev/null 2>&1; then
        print_success "Dev-Frontend gestartet (PID: $FRONTEND_PID)"
        print_info "Admin-Modus verfügbar auf: http://localhost:3000"
    else
        print_warning "Dev-Frontend startet noch... (Prüfe frontend_dev.log)"
    fi
fi

# Schritt 8: Zusammenfassung
print_header "✅ Setup abgeschlossen!"

echo -e "${GREEN}════════════════════════════════════════${NC}"
echo -e "${GREEN}Production Setup erfolgreich!${NC}"
echo -e "${GREEN}════════════════════════════════════════${NC}"
echo ""
echo -e "${BLUE}📋 Zusammenfassung:${NC}"
echo -e "   Episode: ${YELLOW}$EPISODE_KEY${NC}"
echo -e "   Cloudflare Tunnel URL: ${YELLOW}$TUNNEL_URL${NC}"
echo -e "   Backend: ${GREEN}http://localhost:$BACKEND_PORT${NC}"
echo -e "   Frontend (Dev/Admin): ${GREEN}http://localhost:3000${NC}"
echo ""
echo -e "${BLUE}📝 Nächste Schritte:${NC}"
echo -e "   1. Admin-Modus öffnen: ${YELLOW}http://localhost:3000${NC}"
if [ -z "$DEPLOYMENT_TRIGGERED" ]; then
    echo -e "   2. Frontend deployen: ${YELLOW}GitHub → Actions → 'Deploy to GitHub Pages' → Run workflow${NC}"
    echo -e "      (Verwendet das GitHub Secret für den Build auf GitHub)"
fi
echo -e "   3. Listener starten: ${YELLOW}uv run python listener.py $EPISODE_KEY${NC}"
echo ""
echo -e "${BLUE}ℹ️  Wichtig:${NC}"
echo -e "   - Lokaler Build (dist/): Nur für Tests, nicht deployed"
echo -e "   - GitHub Actions Build: Verwendet GitHub Secret, wird zu GitHub Pages deployed"
echo -e "   - Nach Secret-Update: Deployment muss ausgelöst werden (manuell oder automatisch)"
echo ""
echo -e "${BLUE}🛑 Beenden:${NC}"
echo -e "   ${YELLOW}./stop_production.sh${NC} (stoppt alle Prozesse)"
echo ""
