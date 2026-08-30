# Onboarding auf einem neuen Rechner

Kurzanleitung, um an diesem Projekt auf einem **neuen PC** weiterzuarbeiten.
Der Code liegt vollständig in git — das Einzige, was fehlt, ist **Nicht-git-Zustand**
(Secrets + ein paar Env-Variablen). Diese Datei listet genau das.

## 1. Code holen & Abhängigkeiten

```bash
git clone <repo-url> fact_check && cd fact_check
uv sync                       # Python-Deps (nicht pip)
cd frontend && bun install    # Frontend-Deps (nicht npm)
```

Alles Weitere (Commands, Architektur, Workflow) steht in [`../CLAUDE.md`](../CLAUDE.md).

## 2. `.env` übertragen (das Wichtigste)

`.env` ist gitignored und wird **nicht** geklont. Ohne sie läuft nichts.
Kopiere die Datei **sicher** vom alten Rechner (Passwort-Manager / verschlüsselter
Transfer) — **nie** über git/Chat/E-Mail im Klartext.

Benötigte Variablen (nur Namen — Werte vom alten Rechner übernehmen):

**Secrets**
- `ASSEMBLYAI_API_KEY` — Transkription
- `GEMINI_API_KEY` (oder `GOOGLE_API_KEY`) — LLM (primär)
- `TAVILY_API_KEY` — Websuche
- `REQUESTY_API_KEY` — **Provider-Fallback** (Claude via Requesty, EU)

**Modell-Config**
- `GEMINI_MODEL_CLAIM_EXTRACTION=gemini-2.5-pro`
- `GEMINI_MODEL_FACT_CHECKER=gemini-2.5-pro`
- `GEMINI_MODEL_SELF_CRITIQUE=gemini-2.5-flash`
- `GEMINI_MODEL_FACT_CHECKER_FALLBACK=` — **leer lassen!** (überspringt den schwachen
  Gemini-Flash-Zwischenschritt; der Fact-Checker fällt direkt auf Claude zurück)
- `TAVILY_SEARCH_DEPTH`, `TAVILY_MAX_RESULTS` — Suchparameter

## 3. Cross-Provider-Fallback (Kontext)

Um einen kompletten Google-Ausfall (Outage/Quota/Auth) beim Live-Event zu überstehen,
hängt `backend/services/llm_base.py` (`build_model`) ein **Nicht-Google-Modell** als
letzte Ebene an — Claude Opus 4.8 über Requesty in der EU.

Aktive Ketten:
- **Fact-Checker:** `gemini-2.5-pro → claude-opus-4-8@eu`
- **Claim-Extraktion:** `gemini-2.5-pro → claude-opus-4-8@eu`

Steuer-Env (Defaults funktionieren ohne Setzen):
- `PROVIDER_FALLBACK_ENABLED` (default `true`; `false` deaktiviert komplett)
- `PROVIDER_FALLBACK_MODEL` (default `claude-opus-4-8@eu` — Requesty-**Router** über
  alle EU-Backends, mehr Redundanz als ein einzelner gepinnter Anbieter)
- `REQUESTY_BASE_URL` (default `https://router.requesty.ai/v1`)

Greift nur, wenn `REQUESTY_API_KEY` gesetzt ist — fehlt er, läuft die Pipeline sauber
Google-only weiter.

## 4. Deployment (wichtig auf neuem Rechner!)

Der Backend-Deploy erfolgt über `deploy/deploy.sh` (`git reset --hard origin/main`
auf der VPS → deployt, **was auf `origin/main` liegt**, nicht lokale Dateien).

Auf dem **alten** Rechner löst ein `~/.zshrc`-`git`-Wrapper `deploy.sh` automatisch
nach `git push` aus. **Auf dem neuen Rechner existiert dieser Wrapper nicht** — dort
also nach dem Push **manuell** `./deploy/deploy.sh` laufen lassen (oder den Wrapper
neu einrichten).

Zusätzlich: Die VPS hat eine **eigene** `.env`. Neue Secrets (z. B. `REQUESTY_API_KEY`)
müssen dort separat in `/opt/fact_check/.env` eingetragen und der Dienst neu gestartet
werden — `deploy.sh` fasst die `.env` nicht an.

## 5. Was du NICHT übertragen musst

Lokale Scratch-Dateien, `factcheck.db`, `pdfs/`, diverse `*.md`-Notizen im Root usw.
sind nicht nötig — sie sind entweder gitignored oder lokaler Arbeitsstand.
