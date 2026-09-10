#!/bin/bash
# LEGACY deploy path — the source-checkout one. Superseded by the image deploy
# (deploy/pull-deploy.sh, driven by factcheck-deploy.timer on the VPS). Kept only
# until the container deploy has run a few live evenings; delete it after that.
#
# ⚠️  DANGER: this runs `git reset --hard origin/main` inside /opt/fact_check.
#     Anything uncommitted on the server — an edited prompt, a patched script, a
#     scratch file inside the repo — is deleted without a prompt. Do not use the
#     VPS checkout as a workplace, and check `ssh hostinger 'cd /opt/fact_check &&
#     git status --porcelain'` before running this.
#
# Update the deployed backend on the VPS: fetch, hard-reset to origin/main, sync deps, restart service.
# Uses reset --hard (not pull) so a squashed/force-pushed main does not fail on non-fast-forward.
set -e
VPS=hostinger
REPO=/opt/fact_check
ssh "$VPS" "cd $REPO && git fetch --prune origin && git reset --hard origin/main && /root/.local/bin/uv sync && systemctl restart factcheck-backend && systemctl --no-pager status factcheck-backend | head -5"
echo "Smoke test:"
# Poll health for a bit — the service needs a moment to boot, so an immediate
# curl can flash a false 502 right after restart.
HEALTH_URL=https://api.live-faktencheck.de/api/health
for i in $(seq 1 15); do
  if curl -fsS "$HEALTH_URL"; then
    echo
    echo "Health OK after ~$((i*2))s"
    exit 0
  fi
  sleep 2
done
echo
echo "Health check FAILED after ~30s" >&2
exit 1
