#!/bin/bash

# Script zum Committen der Fact-Check JSON-Dateien für GitHub Pages
# Führt die Dateien zu Git hinzu und committed sie

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

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

DATA_DIR="frontend/public/data"

echo -e "\n${BLUE}════════════════════════════════════════${NC}"
echo -e "${BLUE}💾 Committe Fact-Check JSON-Dateien${NC}"
echo -e "${BLUE}════════════════════════════════════════${NC}\n"

# Prüfe ob JSON-Dateien vorhanden sind
if [ ! -d "$DATA_DIR" ] || [ -z "$(ls -A $DATA_DIR/*.json 2>/dev/null)" ]; then
    print_warning "Keine JSON-Dateien gefunden in $DATA_DIR"
    exit 0
fi

# Zeige vorhandene Dateien
print_info "Gefundene JSON-Dateien:"
for file in $DATA_DIR/*.json; do
    if [ -f "$file" ]; then
        episode=$(basename "$file" .json)
        count=$(python3 -c "import json; data=json.load(open('$file')); print(len(data))" 2>/dev/null || echo "?")
        echo "   - $episode: $count Fact-Checks"
    fi
done

echo ""
read -p "Möchtest du diese Dateien committen und pushen? (j/n): " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[JjYy]$ ]]; then
    print_info "Abgebrochen."
    exit 0
fi

# Füge Dateien zu Git hinzu
print_info "Füge JSON-Dateien zu Git hinzu..."
git add $DATA_DIR/*.json

# Prüfe ob es Änderungen gibt
if git diff --staged --quiet; then
    print_warning "Keine Änderungen zum Committen."
    exit 0
fi

# Committe
EPISODE_KEYS=$(ls $DATA_DIR/*.json 2>/dev/null | xargs -n1 basename | sed 's/.json$//' | tr '\n' ',' | sed 's/,$//')
COMMIT_MSG="Update fact checks: $EPISODE_KEYS"

print_info "Committte mit Nachricht: $COMMIT_MSG"
git commit -m "$COMMIT_MSG"

# Frage ob gepusht werden soll
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

echo ""
print_success "Fertig!"
