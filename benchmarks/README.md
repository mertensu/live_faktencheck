# Pipeline-Benchmarks

Wiederholbare A/B-Tests für Timing, Qualität und Kosten der Fact-Check-Pipeline.
Gedacht als Ausgangspunkt, wenn ein Modellwechsel oder eine Konfig-Änderung
bewertet werden soll.

## Warum auf dem VPS?

Die API-Keys (Gemini, Tavily, Requesty) liegen nur in `/opt/fact_check/.env` auf
dem VPS, nicht lokal. Die Skripte machen echte, kostenpflichtige API-Calls.

```bash
ssh hostinger        # Zugang, siehe CLAUDE.md
```

## `model_ab.py` — Modellvergleich

Misst pro Lauf:
- **[A]** LLM-Vorstufen: Sprecher-Auflösung + Claim-Extraktion + Auswahl (Timing)
- **[B]** Check-Stufe: 6 Claims parallel (Timing + Verdikte + Quellenzahl)
- **[C]** Token-Verbrauch eines Checks → hochgerechnete Kosten

Der Harness patcht `build_model` **zur Laufzeit** so, dass Modellnamen mit `@`
(z. B. `gemini-3.8-flash@eu`) über Requesty (EU) laufen. Produktionscode wird
dabei **nicht** verändert.

### Ausführen

```bash
# Baseline (aktuelle Live-Config aus .env)
ssh hostinger "cd /opt/fact_check && AB_LABEL='baseline' \
  PYTHONPATH=/opt/fact_check /root/.local/bin/uv run python benchmarks/model_ab.py"

# Kandidat: Extraktion + Check auf Requesty-EU-Flash, Critique unverändert
ssh hostinger "cd /opt/fact_check && AB_LABEL='3.8-flash@eu' \
  GEMINI_MODEL_CLAIM_EXTRACTION='gemini-3.8-flash@eu' \
  GEMINI_MODEL_FACT_CHECKER='gemini-3.8-flash@eu' \
  PYTHONPATH=/opt/fact_check /root/.local/bin/uv run python benchmarks/model_ab.py"
```

Bei einem Modell, das länger als 120 s braucht, läuft der Aufruf im Hintergrund
weiter; die Ausgabe landet in der von der Shell genannten Datei.

### Env-Stellschrauben

| Variable | Wirkung |
|---|---|
| `AB_LABEL` | Anzeigename des Laufs |
| `GEMINI_MODEL_CLAIM_EXTRACTION` | steuert Resolve **und** Extract |
| `GEMINI_MODEL_FACT_CHECKER` | steuert die Check-Stufe |
| `GEMINI_MODEL_SELF_CRITIQUE` | steuert die Self-Critique |
| `FC_ENV` | Pfad zur `.env` (Default `/opt/fact_check/.env`) |
| `RATE_IN` / `RATE_OUT` | $/1M Token, für Modelle ohne Eintrag in `RATES` |

Rate-Cards (`$/1M Token`) stehen in `model_ab.py` unter `RATES` — bei neuem
Modell dort ergänzen oder `RATE_IN`/`RATE_OUT` setzen.

## Stolperfallen (aus Erfahrung)

- `uv` ist im nicht-interaktiven SSH **nicht im PATH** → voller Pfad
  `/root/.local/bin/uv`. Verifizieren mit `ssh hostinger "command -v uv"`.
- `PYTHONPATH=/opt/fact_check` ist Pflicht: Bei einem Skript liegt dessen eigenes Verzeichnis
  auf `sys.path`, nicht das Projekt-Root — ohne die Variable schlägt schon `import backend` fehl.
- `load_dotenv` sucht relativ zum Skript, nicht zum CWD → das Skript setzt den
  `.env`-Pfad explizit.
- Ergebnis-Dict nutzt **englische** Keys: `consistency`, `sources`, `evidence`
  (der deutsche `quellen` entsteht erst beim DB-Mapping in `utils.py`).
- **Hohe Streuung:** die Check-Stufe schwankt je nach API-Last um ±20–30 s.
  Für belastbare Aussagen 2–3 Läufe mitteln.
- Das Überschreiben von Produktionscode/-config blockt der Auto-Mode-Klassifizierer.
  Diese Benchmarks ändern bewusst nichts an der laufenden App.

## Erkenntnisse bisher (Sep 2026)

- **Engpass ist nicht die Modell-Inferenz**, sondern die Tavily-Suchrunden pro
  Check. `FACT_CHECK_MAX_WORKERS` über 4 zu erhöhen brachte **keinen** Gewinn
  (workers=4: ~83 s, workers=6: ~89 s für 6 Claims).
- **`gemini-3.8-flash@eu`** vs `gemini-2.5-pro`: ~**80 % günstiger** pro Block,
  Verdikte auf einfacher Stichprobe **identisch**, aber **nicht schneller**
  (Requesty-Router = zusätzlicher Netz-Hop). Attraktiv für Kosten + EU-Residenz,
  vor Umstellung aber Qualität auf **schwierigeren** Claims prüfen.
- End-to-End mit pro (Transkript → Ergebnis): ~1:30 (voller Block), ~1:00
  (leichter Block); ab gesprochenem Wort inkl. 60-s-Fenster ~1:45–2:30.
