#!/bin/bash
# Update the deployed backend on the VPS: pull, sync deps, restart service.
set -e
VPS=hostinger
REPO=/opt/fact_check
ssh "$VPS" "cd $REPO && git pull && /root/.local/bin/uv sync && systemctl restart factcheck-backend && systemctl --no-pager status factcheck-backend | head -5"
echo "Smoke test:"
curl -fsS https://api.live-faktencheck.de/api/health && echo
