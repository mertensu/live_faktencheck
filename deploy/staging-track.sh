#!/bin/bash
# Point the single staging backend at a branch's CI-built image, and deploy it now.
# Runs ON THE VPS.
#
#   deploy/staging-track.sh <branch>      # e.g. live-fast-lane
#
# There is one staging box, so it follows one branch at a time; re-run this to switch.
# The branch's image must already be published — CI publishes ghcr.io/<repo>:branch-<slug>
# on every push to a same-repo PR (see .github/workflows/ci.yml). After this, the
# factcheck-deploy-staging.timer keeps staging on that branch's latest push automatically.
set -euo pipefail

branch=${1:?usage: staging-track.sh <branch>}
# Same slug rule as the CI tag: lowercase, '/' -> '-', drop tag-illegal chars.
slug=$(printf '%s' "$branch" | tr '[:upper:]' '[:lower:]' | tr '/' '-' | tr -cd 'a-z0-9._-')
env_file=/opt/fact_check/staging/deploy.env

mkdir -p "$(dirname "$env_file")"
echo "IMAGE=ghcr.io/mertensu/live_faktencheck:branch-$slug" > "$env_file"
echo "staging now tracks branch-$slug"

# Deploy immediately rather than waiting for the next timer tick.
systemctl start factcheck-deploy-staging.service
systemctl status --no-pager -n 20 factcheck-deploy-staging.service || true
