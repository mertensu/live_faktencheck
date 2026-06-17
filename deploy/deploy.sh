#!/bin/bash
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
