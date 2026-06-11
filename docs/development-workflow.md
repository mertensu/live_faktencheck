# Development Workflow

Test the full pipeline locally — same tools as production, but without the Cloudflare tunnel. Nothing goes live.

---

## Running locally

```bash
# Start backend + admin UI (no tunnel)
./start_dev.sh atalay-2026-02-09   # inherits Atalay's speakers and config
```

Open the admin UI at **http://localhost:3000**, switch to Admin-Modus, and click "Aufnahme starten" to start the browser mic recorder.

- Review extracted claims at **http://localhost:3000** (Admin UI)
- Approve claims → fact-checking runs automatically
- Results visible locally only — nothing appears on the public domain

Stop with Ctrl-C in each terminal.
