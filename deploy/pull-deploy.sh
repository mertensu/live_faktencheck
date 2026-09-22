#!/bin/bash
# Runs ON THE VPS (systemd timer or by hand). Pulls the image CI published from main
# and restarts the container. Nothing connects inward: the firewall stays closed.
#
# Env overrides (used by the staging invocation):
#   COMPOSE_FILE      default /opt/fact_check/deploy/docker-compose.yml
#   HEALTH_URL        default http://127.0.0.1:5000/api/health
#   STATE_DIR         default /var/lib/factcheck
#   DEPLOY_MAX_DEFER  seconds a pending restart may wait for a lull before going
#                     anyway (default 3600; 0 disables deferral entirely)
#
# Safety valves, in order:
#   1. A hold file pauses automatic deploys (see HOLD_FILE) — a hard freeze.
#   2. Nothing happens when the running container is already on the pulled image.
#   3. In-flight work defers the restart (up to DEPLOY_MAX_DEFER), so a queued or
#      in-progress fact-check is not dropped — the timer retries and lands it in the
#      next lull. "In flight" is /api/health's in_flight (queued claim batches +
#      processing blocks), NOT active_sessions — that one is a lifecycle flag that
#      stays set for days after a session and would defer every deploy forever.
#      There is no single quiet evening in continuous use; this waits for a real gap.
#   4. A failed health check rolls back to the previously running image automatically.
set -euo pipefail

COMPOSE_FILE=${COMPOSE_FILE:-/opt/fact_check/deploy/docker-compose.yml}
HEALTH_URL=${HEALTH_URL:-http://127.0.0.1:5000/api/health}
STATE_DIR=${STATE_DIR:-/var/lib/factcheck}
IMAGE=${IMAGE:-ghcr.io/mertensu/live_faktencheck:latest}
HOLD_FILE=${HOLD_FILE:-/opt/fact_check/deploy-hold}
DEPLOY_MAX_DEFER=${DEPLOY_MAX_DEFER:-3600}

# One state file per compose project, so staging never overwrites production's rollback target.
STATE_KEY=$(basename "$COMPOSE_FILE" .yml)
PREVIOUS_FILE="$STATE_DIR/$STATE_KEY.previous-image"
DEFER_FILE="$STATE_DIR/$STATE_KEY.deferred-since"

log() { echo "[$(date -Is)] $*"; }

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

digest_of() {
  docker image inspect "$1" --format '{{index .RepoDigests 0}}' 2>/dev/null || true
}

# The image ref the running container was started from. pull-deploy always starts
# it with FACTCHECK_IMAGE=<digest>, so .Config.Image is that pinned RepoDigest and
# compares directly against digest_of :latest — independent of the pull delta.
running_digest() {
  local cid
  cid=$(compose ps -q backend 2>/dev/null || true)
  [[ -n "$cid" ]] || return 0
  docker inspect --format '{{.Config.Image}}' "$cid" 2>/dev/null || true
}

in_flight() {
  curl -fsS "$HEALTH_URL" 2>/dev/null \
    | sed -n 's/.*"in_flight"[[:space:]]*:[[:space:]]*\([0-9]\{1,\}\).*/\1/p'
}

wait_healthy() {
  for _ in $(seq 1 20); do
    if curl -fsS -o /dev/null "$HEALTH_URL"; then return 0; fi
    sleep 3
  done
  return 1
}

if [[ -f "$HOLD_FILE" ]]; then
  log "hold file $HOLD_FILE present — skipping deploy"
  exit 0
fi

mkdir -p "$STATE_DIR"

log "pulling $IMAGE"
# Pull exactly the ref $IMAGE names, not the compose file's default: staging tracks a
# per-branch tag (see factcheck-deploy-staging.service), and $IMAGE is the single source
# of truth for what to deploy. For prod, $IMAGE is :latest — identical to before.
FACTCHECK_IMAGE="$IMAGE" compose pull --quiet
target=$(digest_of "$IMAGE")
running=$(running_digest)

if [[ -n "$running" && "$running" == "$target" ]]; then
  log "already on $target — nothing to do"
  rm -f "$DEFER_FILE"
  exit 0
fi

# A new image is waiting. Hold the restart while work is in flight so a queued or
# in-progress fact-check is not dropped — but not forever: after DEPLOY_MAX_DEFER we go anyway.
if [[ "$DEPLOY_MAX_DEFER" -gt 0 ]]; then
  busy=$(in_flight)
  if [[ "${busy:-0}" -gt 0 ]]; then
    now=$(date +%s)
    [[ -f "$DEFER_FILE" ]] || echo "$now" > "$DEFER_FILE"
    since=$(cat "$DEFER_FILE" 2>/dev/null || echo "$now")
    waited=$(( now - since ))
    if (( waited < DEPLOY_MAX_DEFER )); then
      log "$busy item(s) in flight — deferring $target (${waited}s/${DEPLOY_MAX_DEFER}s)"
      exit 0
    fi
    log "$busy item(s) in flight but deferred ${waited}s — deploying anyway"
  fi
fi
rm -f "$DEFER_FILE"

# Remember what worked before switching, so the rollback target survives a reboot.
if [[ -n "$running" ]]; then
  echo "$running" > "$PREVIOUS_FILE"
fi

log "starting $target"
FACTCHECK_IMAGE="$target" compose up -d

if wait_healthy; then
  log "healthy on $target"
  docker image prune -f --filter "until=168h" >/dev/null || true
  exit 0
fi

log "health check failed after ~60s"
if [[ -s "$PREVIOUS_FILE" ]]; then
  previous=$(cat "$PREVIOUS_FILE")
  log "rolling back to $previous"
  FACTCHECK_IMAGE="$previous" compose up -d
  if wait_healthy; then
    log "rollback healthy — the new image is broken, the service is back on the old one"
  else
    log "ROLLBACK ALSO UNHEALTHY — service is down, needs a human"
  fi
else
  log "no previous image recorded — cannot roll back automatically"
fi
exit 1
