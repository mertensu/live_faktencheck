#!/bin/bash
# Update the deployed backend on the VPS: fetch, hard-reset to origin/main, sync deps, restart service.
# Uses reset --hard (not pull) so a squashed/force-pushed main does not fail on non-fast-forward.
set -e
VPS=hostinger
REPO=/opt/fact_check
ssh "$VPS" "cd $REPO && git fetch --prune origin && git reset --hard origin/main && /root/.local/bin/uv sync && systemctl restart factcheck-backend && systemctl --no-pager status factcheck-backend | head -5"
echo "Smoke test:"
curl -fsS https://api.live-faktencheck.de/api/health && echo
