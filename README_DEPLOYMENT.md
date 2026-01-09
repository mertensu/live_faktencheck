# Deployment-Anleitung: Live Fact-Check auf GitHub Pages

## Setup für Live-Updates

Das Frontend lädt die Daten **live vom Backend**, auch in Produktion auf GitHub Pages.

### 1. Backend öffentlich machen

Das Backend muss über einen Tunnel erreichbar sein:

#### Option A: ngrok
```bash
ngrok http 5000
```
Kopiere die HTTPS-URL (z.B. `https://abc123.ngrok.io`)

#### Option B: Cloudflare Tunnel
```bash
cloudflared tunnel --url http://localhost:5000
```

### 2. Backend-URL konfigurieren

#### Für lokale Entwicklung:
Keine Konfiguration nötig, verwendet automatisch `http://localhost:5000`

#### Für GitHub Pages (Produktion):

**Option 1: Environment Variable beim Build**
```bash
VITE_BACKEND_URL=https://abc123.ngrok.io npm run build
```

**Option 2: .env Datei** (wird nicht committed)
Erstelle `frontend/.env.production`:
```
VITE_BACKEND_URL=https://abc123.ngrok.io
```

**Option 3: GitHub Actions Secret**
1. Gehe zu GitHub Repository → Settings → Secrets and variables → Actions
2. Füge Secret hinzu: `VITE_BACKEND_URL` = `https://abc123.ngrok.io`
3. Passe `.github/workflows/deploy.yml` an, um das Secret zu verwenden

### 3. GitHub Actions Workflow anpassen

Falls du Option 3 verwendest, passe `.github/workflows/deploy.yml` an:

```yaml
- name: Build
  run: npm run build
  env:
    VITE_BACKEND_URL: ${{ secrets.VITE_BACKEND_URL }}
```

### 4. Workflow

1. **Während der Sendung:**
   - Backend läuft lokal auf Port 5000
   - ngrok/Cloudflare Tunnel macht es öffentlich
   - Frontend auf GitHub Pages lädt live vom Backend (alle 2 Sekunden)
   - JSON-Dateien werden als Backup gespeichert

2. **Nach der Sendung:**
   - Optional: JSON-Dateien committen für Offline-Zugriff
   - Tunnel kann geschlossen werden

### 5. Fallback-Mechanismus

Wenn das Backend nicht erreichbar ist:
- Frontend versucht automatisch, JSON-Dateien von GitHub Pages zu laden
- Diese müssen vorher committed worden sein

## Troubleshooting

**Frontend zeigt keine Daten:**
- Prüfe ob Backend läuft: `curl http://localhost:5000/api/health`
- Prüfe ob Tunnel läuft: `curl https://abc123.ngrok.io/api/health`
- Prüfe Browser-Konsole auf CORS-Fehler
- Prüfe ob `VITE_BACKEND_URL` korrekt gesetzt ist

**CORS-Fehler:**
- Backend hat bereits `CORS(app)` - sollte funktionieren
- Falls nicht: Prüfe ob Backend auf `0.0.0.0` läuft (nicht nur `localhost`)

