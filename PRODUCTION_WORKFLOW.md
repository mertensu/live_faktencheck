# Produktions-Workflow: Live Fact-Check Sendung

## ⚡ Schnellstart (Automatisiert)

**Für eine schnelle Einrichtung verwende das automatische Setup-Script:**

```bash
# Starte alles automatisch (ngrok, Frontend-Build, Backend)
./start_production.sh <episode-key>

# Beispiel:
./start_production.sh maischberger-2025-09-19
```

Das Script führt automatisch aus:
1. ✅ Cloudflare Tunnel starten (falls nicht läuft)
2. ✅ Cloudflare Tunnel URL extrahieren
3. ✅ GitHub Secret aktualisieren (falls GitHub CLI installiert)
4. ✅ **Deployment automatisch auslösen** (wenn Secret aktualisiert wurde)
5. ✅ Frontend mit korrekter URL bauen
6. ✅ Backend starten
7. ✅ Episode im Backend setzen
8. ✅ Dev-Frontend starten (für Admin-Modus)

**⚠️ Wichtig:** Cloudflare Tunnel URLs ändern sich bei jedem Neustart. Das Script aktualisiert automatisch das GitHub Secret und löst das Deployment aus, damit GitHub Pages immer die aktuelle URL verwendet.

**Beenden:**
```bash
./stop_production.sh
```

---

## 📋 Manueller Workflow

Falls du die Schritte manuell ausführen möchtest:

## Vorbereitung (einmalig)

1. **GitHub Secret setzen:**
   - GitHub Repository → Settings → Secrets and variables → Actions
   - Neues Secret: `VITE_BACKEND_URL` (wird später mit ngrok-URL gefüllt)

## Workflow für jede Sendung

### Schritt 1: Config vorbereiten
```bash
# Öffne config.py und füge neue Episode hinzu:
# z.B. "maischberger-2025-10-15": { ... }

# Committe und pushe (optional, aber empfohlen für Dokumentation)
git add config.py
git commit -m "Add episode: maischberger-2025-10-15"
git push
```

**Hinweis:** Push ist optional, da Config dynamisch vom Backend geladen wird. Aber für Dokumentation im Repo empfohlen.

### Schritt 2: Cloudflare Tunnel starten
```bash
cloudflared tunnel --url http://localhost:5000
```

**Wichtig:** 
- Kopiere die HTTPS-URL (z.B. `https://xxxxx.trycloudflare.com`)
- **⚠️ Die URL ändert sich bei jedem Neustart!**
- Cloudflare Tunnel zeigt keine Warning-Seite im Browser (im Gegensatz zu ngrok)

### Schritt 3: GitHub Secret aktualisieren und Deployment auslösen
**⚠️ WICHTIG:** Nach jedem Neustart des Cloudflare Tunnels muss:
1. Das GitHub Secret `VITE_BACKEND_URL` aktualisiert werden
2. Das GitHub Pages Deployment neu ausgelöst werden

**Automatisch (empfohlen):**
- Das `start_production.sh` Script macht das automatisch, wenn GitHub CLI installiert und authentifiziert ist

**Manuell:**
- GitHub Repository → Settings → Secrets and variables → Actions
- Bearbeite `VITE_BACKEND_URL` mit der neuen Tunnel-URL
- GitHub → Actions → 'Deploy to GitHub Pages' → Run workflow

### Schritt 4: Production-Frontend bauen und deployen

**Option A: Manuell über GitHub Actions UI (empfohlen, kein Commit nötig)**
1. Gehe zu GitHub Repository → **Actions** Tab
2. Wähle **"Deploy to GitHub Pages"** Workflow
3. Klicke **"Run workflow"** → **"Run workflow"** Button
4. GitHub Actions:
   - Führt `npm run build` mit `VITE_BACKEND_URL` aus Secrets aus
   - Deployed automatisch zu GitHub Pages

**Option B: Automatisch bei Push**
```bash
# Push zu main löst automatisch Build + Deployment aus
git push
# GitHub Actions:
# 1. Führt `npm run build` mit VITE_BACKEND_URL aus Secrets aus
# 2. Deployed automatisch zu GitHub Pages
```

**Option C: Lokal bauen und manuell deployen**
```bash
cd frontend
# 1. Build erstellen
VITE_BACKEND_URL=https://abc123.ngrok.io npm run build

# 2. Manuell zu GitHub Pages deployen (z.B. mit gh-pages)
# ODER: dist/ Ordner manuell zu gh-pages Branch pushen
```

**Hinweis:** 
- `npm run build` erstellt nur die Build-Dateien (im `dist/` Ordner)
- "Deployen" bedeutet, diese Dateien auf GitHub Pages zu veröffentlichen
- Mit GitHub Actions passiert beides automatisch beim Push
- Dieses Frontend ist für **Endnutzer** auf GitHub Pages

### Schritt 5: Dev-Frontend starten (für Admin-Modus)

**Wichtig:** Für den Admin-Modus brauchst du den lokalen Dev-Server:

```bash
cd frontend
npm run dev
```

**Prüfe:** Dev-Server sollte auf `http://localhost:3000` laufen
- **Production-Frontend:** GitHub Pages (für Endnutzer)
- **Dev-Frontend:** `http://localhost:3000` (für Admin-Modus, lokal)
- Beide nutzen das gleiche Backend (via ngrok)

### Schritt 6: Backend starten
```bash
# Im Projekt-Root
uv run python backend/app.py
```

**Prüfe:** Backend sollte auf `http://localhost:5000` laufen
```bash
curl http://localhost:5000/api/health
# Sollte zurückgeben: {"status": "ok"}
```

### Schritt 7: Listener starten
```bash
# Mit spezifischem Episode-Key
uv run python listener.py maischberger-2025-10-15

# Oder mit Umgebungsvariable
SHOW=maischberger-2025-10-15 uv run python listener.py
```

**Wichtig:** Der Episode-Key muss mit dem Config-Eintrag übereinstimmen!

## Während der Sendung

- **Listener** nimmt Audio auf und sendet Blöcke an N8N
- **N8N** sendet pending claims → Backend → **Admin-Modus (localhost:3000)** zeigt sie
- **Du** wählst Claims im Admin-Modus aus → sendest an N8N
- **N8N** verarbeitet → sendet finale Urteile → Backend → **Production-Frontend (GitHub Pages)** zeigt sie live

**Zwei Frontends parallel:**
- `http://localhost:3000` → Admin-Modus (nur lokal, für dich)
- GitHub Pages → Production-Frontend (öffentlich, für Endnutzer)

## Nach der Sendung

1. **Listener beenden:** `Ctrl+C` (Daten werden nicht gesendet)
2. **Dev-Frontend beenden:** `Ctrl+C` im Frontend-Terminal (falls noch läuft)
3. **ngrok Tunnel beenden:** `Ctrl+C` im ngrok-Terminal
4. **Backend beenden:** `Ctrl+C` im Backend-Terminal
4. **Optional:** JSON-Dateien committen für Offline-Zugriff:
   ```bash
   git add frontend/public/data/*.json
   git commit -m "Update fact checks for maischberger-2025-10-15"
   git push
   ```

## Checkliste vor Sendung

- [ ] Config-Eintrag in `config.py` hinzugefügt
- [ ] ngrok läuft und URL notiert
- [ ] `VITE_BACKEND_URL` GitHub Secret aktualisiert (oder beim Build gesetzt)
- [ ] **Production-Frontend deployed** (automatisch oder manuell) → GitHub Pages
- [ ] **Dev-Frontend gestartet** (`npm run dev`) → `http://localhost:3000` für Admin-Modus
- [ ] Backend läuft auf Port 5000
- [ ] Listener mit korrektem Episode-Key gestartet
- [ ] Admin-Modus im Dev-Frontend getestet (`http://localhost:3000`)
- [ ] N8N Webhooks konfiguriert

## Troubleshooting

**Production-Frontend (GitHub Pages) zeigt keine Daten:**
- Prüfe ob Backend läuft: `curl http://localhost:5000/api/health`
- Prüfe ob ngrok läuft: `curl https://abc123.ngrok.io/api/health`
- Prüfe Browser-Konsole auf CORS-Fehler
- Prüfe ob `VITE_BACKEND_URL` korrekt gesetzt ist (beim Build)

**Dev-Frontend (localhost:3000) zeigt keine Daten:**
- Prüfe ob Dev-Server läuft: `curl http://localhost:3000`
- Prüfe ob Backend läuft: `curl http://localhost:5000/api/health`
- Dev-Frontend nutzt automatisch `http://localhost:5000` (kein ngrok nötig)

**Admin-Modus zeigt keine Claims:**
- Prüfe ob N8N pending claims sendet: Backend-Logs prüfen
- Prüfe ob Backend erreichbar ist
- Prüfe Browser-Konsole auf Fehler

**Listener findet keine Config:**
- Prüfe ob Episode-Key in `config.py` existiert
- Prüfe ob `DEFAULT_SHOW` korrekt gesetzt ist
- Prüfe Backend-Logs für Config-Fehler

