#!/bin/bash
# Runs ON THE VPS (systemd timer or by hand). Pulls the image CI published from main
# and restarts the container. Nothing connects inward: the firewall stays closed.
#
# Env overrides (used by the staging invocation):
#   COMPOSE_FILE   default /opt/fact_check/deploy/docker-compose.yml
#   HEALTH_URL     default http://127.0.0.1:5000/api/health
#   STATE_DIR      default /var/lib/factcheck
#
# Safety valves, in order:
#   1. A hold file pauses automatic deploys (see HOLD_FILE) — for broadcast evenings.
#   2. Nothing happens when the pulled digest already runs.
#   3. A failed health check rolls back to the previous digest automatically.
set -euo pipefail

COMPOSE_FILE=${COMPOSE_FILE:-/opt/fact_check/deploy/docker-compose.yml}
HEALTH_URL=${HEALTH_URL:-http://127.0.0.1:5000/api/health}
STATE_DIR=${STATE_DIR:-/var/lib/factcheck}
IMAGE=${IMAGE:-ghcr.io/mertensu/live_faktencheck:latest}
HOLD_FILE=${HOLD_FILE:-/opt/fact_check/deploy-hold}

# One state file per compose project, so staging never overwrites production's rollback target.
STATE_KEY=$(basename "$COMPOSE_FILE" .yml)
PREVIOUS_FILE="$STATE_DIR/$STATE_KEY.previous-image"

log() { echo "[$(date -Is)] $*"; }

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

digest_of() {
  docker image inspect "$1" --format '{{index .RepoDigests 0}}' 2>/dev/null || true
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

before=$(digest_of "$IMAGE")
log "pulling $IMAGE"
compose pull --quiet
after=$(digest_of "$IMAGE")

running=$(docker inspect --format '{{.Image}}' "$(compose ps -q backend 2>/dev/null || true)" 2>/dev/null || true)

if [[ -n "$running" && "$before" == "$after" ]]; then
  log "already on $after — nothing to do"
  exit 0
fi

# Remember what worked before switching, so the rollback target survives a reboot.
if [[ -n "$before" ]]; then
  echo "$before" > "$PREVIOUS_FILE"
fi

log "starting $after"
FACTCHECK_IMAGE="$after" docker compose -f "$COMPOSE_FILE" up -d

if wait_healthy; then
  log "healthy on $after"
  docker image prune -f --filter "until=168h" >/dev/null || true
  exit 0
fi

log "health check failed after ~60s"
if [[ -s "$PREVIOUS_FILE" ]]; then
  previous=$(cat "$PREVIOUS_FILE")
  log "rolling back to $previous"
  FACTCHECK_IMAGE="$previous" docker compose -f "$COMPOSE_FILE" up -d
  if wait_healthy; then
    log "rollback healthy — the new image is broken, the service is back on the old one"
  else
    log "ROLLBACK ALSO UNHEALTHY — service is down, needs a human"
  fi
else
  log "no previous image recorded — cannot roll back automatically"
fi
exit 1
