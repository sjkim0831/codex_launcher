#!/usr/bin/env bash
set -euo pipefail

LOG_FILE="${LOG_FILE:-/tmp/carbonet-18000-autostart.log}"
DOCKER_CONTAINER_NAME="${DOCKER_CONTAINER_NAME:-11.2}"
DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-33000}"
DB_NAME="${DB_NAME:-carbonet}"
DB_USER="${DB_USER:-dba}"
MAX_WAIT_SECONDS="${MAX_WAIT_SECONDS:-300}"
SLEEP_SECONDS="${SLEEP_SECONDS:-5}"

log() {
  printf '[carbonet-18000-autostart] %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG_FILE"
}

deadline=$((SECONDS + MAX_WAIT_SECONDS))

log "waiting for docker daemon"
until docker info >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    log "timeout waiting for docker daemon"
    exit 1
  fi
  sleep "$SLEEP_SECONDS"
done

log "waiting for container ${DOCKER_CONTAINER_NAME}"
until [[ "$(docker inspect -f '{{.State.Running}}' "$DOCKER_CONTAINER_NAME" 2>/dev/null || true)" == "true" ]]; do
  if (( SECONDS >= deadline )); then
    log "timeout waiting for container ${DOCKER_CONTAINER_NAME}"
    exit 1
  fi
  sleep "$SLEEP_SECONDS"
done

log "waiting for db port ${DB_HOST}:${DB_PORT}"
until nc -z "$DB_HOST" "$DB_PORT" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    log "timeout waiting for db port ${DB_HOST}:${DB_PORT}"
    exit 1
  fi
  sleep "$SLEEP_SECONDS"
done

log "waiting for db query readiness"
until docker exec "$DOCKER_CONTAINER_NAME" sh -lc "echo 'select 1;' | csql -u ${DB_USER} ${DB_NAME}" >/dev/null 2>&1; do
  if (( SECONDS >= deadline )); then
    log "timeout waiting for db query readiness"
    exit 1
  fi
  sleep "$SLEEP_SECONDS"
done

log "dependencies ready, restarting carbonet 18000"
bash /opt/projects/carbonet/ops/scripts/restart-18000.sh >>"$LOG_FILE" 2>&1
log "restart command finished"
