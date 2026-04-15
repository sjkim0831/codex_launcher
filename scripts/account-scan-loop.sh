#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTANCE_ID="${1:-${CARBONET_INSTANCE_ID:-default}}"
INTERVAL_SEC="${CARBONET_ACCOUNT_SCAN_INTERVAL_SEC:-900}"
LOG_FILE="${CARBONET_ACCOUNT_SCAN_LOG:-/tmp/carbonet-account-scan.log}"

while true; do
  {
    printf '[account-scan-loop] %s instance=%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$INSTANCE_ID"
    python3 "$SCRIPT_DIR/app/server.py" --app-root "$SCRIPT_DIR" scan-accounts --instance "$INSTANCE_ID"
  } >>"$LOG_FILE" 2>&1 || true
  sleep "$INTERVAL_SEC"
done
