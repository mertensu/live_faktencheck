# Live Fakten-Check

Ein Live-Dashboard für Fakten-Checks mit React Frontend und Flask Backend.

## 🚀 Features

- 📊 Live-Updates von N8N Webhook
- 👥 Sprecher nebeneinander dargestellt
- 💬 Behauptungen unter den jeweiligen Sprechern
- 🔽 Expand-Toggle für Urteil, Begründung und Quellen
- ⚙️ Admin-Modus für Claim-Überprüfung
- 🎨 Modernes, responsives Design
- 📱 Mehrere Sendungen (Test, Maischberger, etc.)

## 📁 Projektstruktur

```
fact_check/
├── backend/           # Flask Backend
│   ├── app.py        # Haupt-Backend
│   └── run.sh        # Start-Script
├── frontend/          # React Frontend
│   ├── src/
│   │   ├── App.jsx   # Hauptkomponente mit Routing
│   │   └── ...
│   └── ...
├── listener.py        # Audio-Aufnahme mit VAD
└── ...
```

## 🛠️ Setup

### Backend

```bash
uv sync
uv run python backend/app.py
```

Das Backend läuft dann auf `http://localhost:5000`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Das Frontend läuft dann auf `http://localhost:3000`

## 🌐 GitHub Pages Deployment

Das Frontend ist für GitHub Pages konfiguriert:

- **Base Path**: `/live_faktencheck/`
- **Routes**: `/test`, `/maischberger`
- **Automatisches Deployment**: Via GitHub Actions

### Setup GitHub Pages

1. Repository auf GitHub erstellen
2. Code pushen
3. Settings → Pages → Source: GitHub Actions
4. Nach Push auf `main` wird automatisch deployed

## 📡 N8N Webhook Konfiguration

### Phase 1: Vorab-Liste von Claims

**URL:** `http://localhost:5000/api/fact-checks` (POST)

**Format:**
```json
{
  "block_id": "audio_block_...",
  "timestamp": "...",
  "claims_count": 10,
  "claims": [
    {
      "name": "Sandra Maischberger",
      "claim": "Die Behauptung..."
    }
  ]
}
```

### Phase 2: Verifizierte Claims zurück

**URL:** `http://localhost:5000/api/fact-checks` (POST)

**Format:**
```json
{
  "verified_claims": [
    {
      "claim_data": [
        {
          "output": {
            "speaker": "Gitta Connemann",
            "original_claim": "...",
            "verdict": "Richtig",
            "evidence": "...",
            "sources": ["..."]
          }
        }
      ]
    }
  ]
}
```

### Phase 3: Ausgewählte Claims senden

**URL:** `http://localhost:5678/webhook/verified-claims` (POST)

**Format:**
```json
{
  "block_id": "...",
  "claims": [
    {
      "name": "Gitta Connemann",
      "claim": "..."
    }
  ],
  "timestamp": "..."
}
```

## 🎯 Verwendung

### Lokal

1. Backend starten: `uv run python backend/app.py`
2. Frontend starten: `cd frontend && npm run dev`
3. Öffne `http://localhost:3000`
4. Wähle eine Sendung (Test, Maischberger)

### Admin-Modus

1. Im Frontend auf "⚙️ Admin-Modus" klicken
2. Pending Claims werden automatisch geladen
3. Claims per Checkbox auswählen
4. "📤 X Claims senden" klicken

## 📝 Sprecher anpassen

Die Sprecher können in `frontend/src/App.jsx` im Array `SPEAKERS` angepasst werden.

## 🔧 Entwicklung

- **Backend**: Flask mit CORS
- **Frontend**: React + Vite + React Router
- **Audio**: PyAudio + Silero VAD
- **Deployment**: GitHub Pages (Frontend) + Lokal/Cloud (Backend)

## 📄 Lizenz

[Deine Lizenz hier]
