# Development Workflow

Test the full pipeline locally — same tools as production, but without the Cloudflare tunnel. Nothing goes live.

---

## Running locally

```bash
# Terminal 1: start backend + admin UI (no tunnel)
./start_dev.sh atalay-2026-02-09   # inherits Atalay's speakers and config

# Terminal 2: start audio capture
uv run python listener.py atalay-2026-02-09
```

- Review extracted claims at **http://localhost:3000** (Admin UI)
- Approve claims → fact-checking runs automatically
- Results visible locally only — nothing appears on the public domain

Stop with `./stop_production.sh` (same stop script works for both modes).
