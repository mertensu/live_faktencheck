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

## Access gate (Phase 3a)

Cost-incurring endpoints (`POST /api/sessions`, `audio-block`, `text-block`,
`approve-claims`, `fact-checks/resend`, `PUT /api/fact-checks/{id}`, pipeline retrigger)
require a valid `X-Access-Code` header. Codes live in the `codes` table and are seeded at
startup from the `ACCESS_CODES` env var **if the table is empty**.

- **Required env** in `/opt/fact_check/.env`:
  `ACCESS_CODES=ulf:SOME_SECRET,anna:OTHER_SECRET` (comma-separated `name:code` pairs).
- **Fail-closed:** if `ACCESS_CODES` is unset and the table is empty, every gated endpoint
  rejects all requests. Set it before/at deploy or the live app stops accepting sessions.
- **Seeding is one-shot** (only when the table is empty). To manage codes on a running DB:
  - add: `sqlite3 backend/data/factcheck.db "INSERT INTO codes (code,name,active,created_at) VALUES ('newcode','name',1,datetime('now'));"`
  - revoke: `sqlite3 backend/data/factcheck.db "UPDATE codes SET active=0 WHERE code='thecode';"`
  - revocation takes effect immediately (no restart).
- After editing `.env`, restart: `systemctl restart factcheck-backend`.
- `listener.py` (laptop live capture) reads the code from its own `ACCESS_CODE` env var.

### Quick Check quota (Phase Q)

`ACCESS_CODES` entries accept an optional third field — `name:code:limit`:
- `name:code`            → default cap of 3 lifetime quick checks
- `name:code:unlimited`  → no cap (use for your own owner code)
- `name:code:<n>`        → custom cap

The quota lives on the `codes` table (`quick_checks_used` / `quick_check_limit`); deleting
a quick-check fact-check row does **not** refund quota.

**On the VPS:** the existing live code was seeded before this column existed, so after
deploying it defaults to a cap of 3. To make your owner code unlimited, either update it
in place:

    sqlite3 /opt/fact_check/backend/data/factcheck.db "UPDATE codes SET quick_check_limit = NULL WHERE name = 'ulf';"

or set `ACCESS_CODES=ulf:SOME_SECRET:unlimited` in `/opt/fact_check/.env` before the **first**
seeding of a fresh codes table (seeding is idempotent and will not re-run on a populated table).

## Provider budget caps (manual — do this once)

The access gate is the primary control; provider-side spend caps are the outer ceiling that
holds even if a code leaks or a bug loops. Set hard limits + alerts in each dashboard:

- **AssemblyAI** — usage/spend cap + alert (transcription).
- **Google / Gemini** (AI Studio or Cloud billing) — budget + alert (claim extraction + fact-check).
- **Tavily** — usage cap/alert (web search).

These are operational settings, not enforced in code.
