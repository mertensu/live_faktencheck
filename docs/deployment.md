# Deployment (VPS)

The backend runs permanently on the Hostinger VPS (`hostinger`, 72.61.83.151) as two
systemd services. The frontend is on Cloudflare Pages and reads the live API at
`https://api.live-faktencheck.de`. There is no local start and no static-JSON export.

## Architecture
- `factcheck-backend` — the container from `deploy/docker-compose.yml` on 127.0.0.1:5000,
  single process. (`factcheck-backend.service`, the pre-container systemd unit that ran
  `uv run uvicorn` from the checkout, is kept as a fallback — see "Updating the backend".)
- `factcheck-deploy.timer` — pulls a new image from GHCR every 5 minutes.
- `cloudflared` — reuses the named tunnel `faktencheck-api`; maps `api.live-faktencheck.de`
  -> localhost:5000 and `staging-api.live-faktencheck.de` -> localhost:5001.
- All of it is isolated from the unrelated NanoClaw stack on the same VPS: own containers,
  no ports 80/443, everything on loopback behind the tunnel.

## First-time provisioning (run on the VPS as root)
0. Install sqlite3: `apt-get update && apt-get install -y sqlite3`
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

Merging a PR into `main` is the deploy. CI builds the image and pushes it to GHCR; the
VPS pulls it. Nothing connects inward — the Hostinger firewall stays closed, and no
laptop is involved.

```
PR merged → CI: test + build → ghcr.io/mertensu/live_faktencheck:latest
                                   ↓ (timer, every 5 min)
                          VPS: deploy/pull-deploy.sh → docker compose up -d
                                   ↓ health check fails?
                          automatic rollback to the previous digest
```

- Watch it land: `ssh hostinger 'journalctl -u factcheck-deploy -n 50'`
- Deploy now instead of waiting: `ssh hostinger '/opt/fact_check/deploy/pull-deploy.sh'`
- **Pause deploys** (broadcast evening): `ssh hostinger 'touch /opt/fact_check/deploy-hold'`,
  resume with `rm`. The timer keeps running and logs that it skipped.

`deploy/deploy.sh` (the old source-checkout deploy from the laptop) still works but is
legacy. It runs `git reset --hard origin/main` on the server and deletes anything
uncommitted there without asking — see the warning in the file itself.

### One-time setup on the VPS

1. `apt-get install -y docker.io docker-compose-plugin`
2. Log in to GHCR — the package is private, so the pull needs a token:
   ```sh
   echo "$GHCR_READ_TOKEN" | docker login ghcr.io -u mertensu --password-stdin
   ```
   Use a classic PAT with **`read:packages` only**, created for the machine. It lands in
   `/root/.docker/config.json`; nothing else on the VPS needs it.
3. Install the timer:
   ```sh
   cp /opt/fact_check/deploy/factcheck-deploy.{service,timer} /etc/systemd/system/
   systemctl daemon-reload && systemctl enable --now factcheck-deploy.timer
   ```
4. Cut over from systemd-uvicorn to the container (do this once, with the show off air):
   ```sh
   systemctl disable --now factcheck-backend      # frees port 5000
   /opt/fact_check/deploy/pull-deploy.sh
   curl -fsS http://127.0.0.1:5000/api/health
   ```
   `factcheck-backend.service` stays in the repo as the fallback: re-enable it after
   `docker compose -f deploy/docker-compose.yml down` if the container path ever has to
   be abandoned mid-evening.

The database path does not move — the container bind-mounts `/opt/fact_check/backend/data`,
so Litestream keeps replicating the same file with no config change.

## Rollback

The failure that gets caught automatically: a new image that does not answer
`/api/health` within ~60s. `pull-deploy.sh` puts the previous digest back and says so in
the journal. Nothing to do by hand.

The failure that does not: an image that is healthy but wrong (bad answers, broken
pipeline). Then go back deliberately:

```sh
ssh hostinger
touch /opt/fact_check/deploy-hold                      # stop the timer re-pulling latest
cd /opt/fact_check
export FACTCHECK_IMAGE=ghcr.io/mertensu/live_faktencheck:<good-commit-sha>
docker compose -f deploy/docker-compose.yml up -d
curl -fsS http://127.0.0.1:5000/api/health
```

Every CI build from `main` is tagged with its commit SHA, so any past commit is a valid
`<good-commit-sha>`. `docker images ghcr.io/mertensu/live_faktencheck` lists what is still
on disk locally; older tags are pulled from GHCR on demand.

Then fix forward on a branch, merge, and `rm /opt/fact_check/deploy-hold` — leaving the
hold file in place is the one way to end up silently running an old build for days.

**A rollback is only real once it has been done.** Do it once on a quiet afternoon:
pin the previous SHA, confirm `/api/health`, un-pin, confirm the timer pulls `latest` back.

## Staging

A second container on the same VPS: `deploy/docker-compose.staging.yml` — port 5001, own
database in `/opt/fact_check/staging/data`, own `/opt/fact_check/.env.staging`, reachable
at `https://staging-api.live-faktencheck.de` through the same tunnel.

```sh
mkdir -p /opt/fact_check/staging/data
cp /opt/fact_check/.env /opt/fact_check/.env.staging   # then: own ACCESS_CODES, own keys
litestream restore -o /opt/fact_check/staging/data/factcheck.db \
  /opt/fact_check/backend/data/factcheck.db            # optional: real data to look at
cloudflared tunnel route dns faktencheck-api staging-api.live-faktencheck.de
systemctl restart cloudflared

COMPOSE_FILE=/opt/fact_check/deploy/docker-compose.staging.yml \
HEALTH_URL=http://127.0.0.1:5001/api/health \
  /opt/fact_check/deploy/pull-deploy.sh
```

Two things to keep straight: staging is **not** replicated by Litestream (its data is
disposable, refill it with the restore above), and it needs its **own** `ACCESS_CODES` —
copying the production code means staging traffic burns the production quota.

## Secrets — three places, three owners

| What | Where | Who has it |
|---|---|---|
| Production keys, `ACCESS_CODES` | `/opt/fact_check/.env` on the VPS | Ulf |
| GHCR read token (pull), `GITHUB_TOKEN` (push, automatic) | `/root/.docker/config.json`, GitHub Actions | Repo admins |
| Dev keys, R2 read token | each contributor's local `.env` | everyone, their own |

**The trap worth knowing:** neither `deploy.sh` nor the image deploy touches
`/opt/fact_check/.env`. A new required env var added in code deploys fine and then fails
at startup on the server. When a PR adds one, add it to the server `.env` **before**
merging — and to `.env.example` in the same PR, so nobody's local setup silently lags.

Also: no inline `# comments` after a value in the server `.env`. Both systemd's
`EnvironmentFile` and compose's `env_file` keep them as part of the value.

## Updating the frontend
Just `git push` to `origin/main` — Cloudflare Pages is wired to the GitHub repo and
builds & deploys the frontend automatically on every push. No manual deploy step.

## Container image

`Dockerfile` in the repo root pins the runtime (Python 3.12 + `uv sync --locked`), so the
same environment runs locally, in CI and in production. CI builds it on every PR and pushes
to GHCR from `main`, tagged with the commit SHA:

```
ghcr.io/mertensu/live_faktencheck:<commit-sha>
ghcr.io/mertensu/live_faktencheck:latest
```

Run it locally against an R2 snapshot (`./scripts/pull-db.sh` first):

```sh
docker build -t factcheck .
docker run --rm -p 5000:5000 --env-file .env \
  -v "$PWD/backend/data:/app/backend/data" factcheck
curl -fsS http://127.0.0.1:5000/api/health
```

Two things the image does not change:
- **Single process.** `backend/state.py` keeps the claim queue and pipeline status in
  process memory — no `--workers`, no `--reload`, and no second replica.
- **The DB stays outside.** `backend/data/` is a volume; the image ships no database.

This is the image production runs — see "Updating the backend" above.

## DB backup (Litestream → Cloudflare R2)

Litestream continuously replicates `backend/data/factcheck.db` to the R2 bucket
`factcheck-backup` (prefix `factcheck/`). It reads the SQLite WAL, so the loss window is
seconds rather than the up-to-24h of the nightly cron it replaced — and it supports
point-in-time restores.

- Service: `litestream.service` (config `/etc/litestream.yml`, mode 600, root only).
  The annotated upstream template is kept at `/etc/litestream.yml.dist`.
- Retention: snapshot every 6h, kept 30 days; 24h of fine-grained history. Litestream 0.5
  defaults to 24h / 5m, which is too short to recover from a delete noticed days later.
- Status: `systemctl status litestream`, `journalctl -u litestream -f`

**Restore on the server:**
```bash
litestream restore -o /tmp/probe.db /opt/fact_check/backend/data/factcheck.db
sqlite3 /tmp/probe.db "PRAGMA integrity_check; SELECT COUNT(*) FROM fact_checks;"
```

**Restore for local development:** `./scripts/pull-db.sh` — uses the read-only R2 token
from your `.env`, no SSH required. It is the same restore path as above, so routine use
keeps recovery exercised. Optional argument: an ISO timestamp for point-in-time restore.

**Archive:** the 96 pre-Litestream daily backups (June–September 2026) live under the
`archive/` prefix of the same bucket. They are not reachable via `litestream restore` —
fetch them with any S3 client, e.g.
`rclone copy r2:factcheck-backup/archive/backup-2026-06-09.db .`

The old nightly cron has been removed; the previous crontab is saved at
`/root/crontab.backup-2026-09-10`.

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

### Live-Audio-Limit (Phase 3b)

Live audio (`POST /api/audio-block`) is metered by **real transcribed seconds** against a
lifetime cap per code, stored on the `codes` table (`audio_seconds_used` / `audio_seconds_limit`,
`NULL` = unlimited). This is independent of the Quick Check quota.

- `LIVE_AUDIO_LIMIT_MINUTES` (default `5`) sets the cap applied at **seeding** as
  `audio_seconds_limit = minutes * 60`. Set it in `/opt/fact_check/.env` before the first seed.
- The `ACCESS_CODES` syntax is **unchanged** (no fourth field). Per-code overrides are DB edits.
- **Fail-closed migration:** the migration backfills **existing** codes to `300` s (5 min) — not
  unlimited. After deploy every old code is capped at 5 minutes of live audio.
- **Owner-code wrinkle (same as Quick Check):** a code already seeded as `unlimited` is **not**
  updated to `NULL` by the idempotent `INSERT OR IGNORE` seed and will sit at the 300 s backfill.
  To make it truly unlimited again:

      sqlite3 /opt/fact_check/backend/data/factcheck.db "UPDATE codes SET audio_seconds_limit = NULL WHERE name = 'ulf';"

- Per-code custom cap (e.g. 30 minutes):

      sqlite3 /opt/fact_check/backend/data/factcheck.db "UPDATE codes SET audio_seconds_limit = 1800 WHERE code = 'thecode';"

- The lifetime counter is deletion-proof: removing fact-checks or sessions does **not** refund
  audio seconds. Reset = DB edit (`UPDATE codes SET audio_seconds_used = 0 WHERE code = '…'`).
- `MAX_AUDIO_BLOCK_BYTES` (default ~25 MB) bounds a single uploaded block (returns `413`); raise
  only if legitimate blocks ever exceed it. The browser recorder sends ~60–180 s blocks, well under.

## Provider budget caps (manual — do this once)

The access gate is the primary control; provider-side spend caps are the outer ceiling that
holds even if a code leaks or a bug loops. Set hard limits + alerts in each dashboard:

- **AssemblyAI** — usage/spend cap + alert (transcription).
- **Google / Gemini** (AI Studio or Cloud billing) — budget + alert (claim extraction + fact-check).
- **Tavily** — usage cap/alert (web search).

These are operational settings, not enforced in code.
