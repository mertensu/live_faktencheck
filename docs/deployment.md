# Deployment (VPS)

The backend runs permanently on the Hostinger VPS (`hostinger`, 72.61.83.151) as two
systemd services. The frontend is on Cloudflare Pages and reads the live API at
`https://api.live-faktencheck.de`. There is no local start and no static-JSON export.

## Architecture
- `factcheck-backend.service` — `uv run uvicorn backend.app:app` on 127.0.0.1:5000, single process.
- `cloudflared` — reuses the named tunnel `faktencheck-api`; maps `api.live-faktencheck.de` -> localhost:5000.
- Both are isolated from the unrelated NanoClaw stack on the same VPS (no Docker, no ports 80/443).

## First-time provisioning (run on the VPS as root)
0. Install system build deps (required so `uv sync` can compile `pyaudio` + `evdev`, which
   are pulled in transitively even though only the laptop's `listener.py` uses them):
   `apt-get update && apt-get install -y build-essential portaudio19-dev python3-dev python3.12-dev sqlite3`
1. Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. `git clone https://github.com/mertensu/live_faktencheck.git /opt/fact_check`
3. Copy secrets/data from the laptop:
   - `scp .env hostinger:/opt/fact_check/.env`
   - `scp backend/data/factcheck.db hostinger:/opt/fact_check/backend/data/factcheck.db`
4. `cd /opt/fact_check && /root/.local/bin/uv sync`
5. Install the backend service:
   - `cp deploy/factcheck-backend.service /etc/systemd/system/`
   - `systemctl daemon-reload && systemctl enable --now factcheck-backend`
   - Verify: `curl -fsS http://127.0.0.1:5000/api/health`
6. Install cloudflared + tunnel (AFTER stopping the laptop tunnel so the named tunnel runs in only one place):
   - `curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cf.deb && dpkg -i /tmp/cf.deb`
   - `mkdir -p /etc/cloudflared`
   - From the laptop: `scp ~/.cloudflared/b18ee8aa-2ea2-4632-abe8-2ab716829574.json hostinger:/etc/cloudflared/` and `scp deploy/cloudflared-config.yml hostinger:/etc/cloudflared/config.yml`
   - `cloudflared service install && systemctl enable --now cloudflared`
   - Verify: `curl -fsS https://api.live-faktencheck.de/api/health`

## Updating the backend
From the laptop: `./deploy/deploy.sh`

## DB backup (cron on the VPS)
`0 4 * * * sqlite3 /opt/fact_check/backend/data/factcheck.db ".backup '/opt/fact_check/backend/data/backup-$(date +\%F).db'"`
