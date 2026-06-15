# Development Workflow

Test the full pipeline locally — same tools as production, but without the Cloudflare tunnel. Nothing goes live.

---

## Running locally

```bash
# Start backend + frontend (no tunnel)
./start_dev.sh atalay-2026-02-09   # inherits Atalay's speakers and config
```

Open the UI at **http://localhost:3000**, unlock with an access code, and (in **Review** mode, or switch to **Pro**) click "Aufnahme starten" to start the browser mic recorder.

- Review and approve extracted claims in **Review** or **Pro** mode
- Approve claims → fact-checking runs automatically
- Results visible locally only — nothing appears on the public domain

Stop with Ctrl-C in each terminal.
