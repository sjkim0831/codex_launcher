#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTANCE_ID="${1:-${CARBONET_INSTANCE_ID:-default}}"

exec python3 "$SCRIPT_DIR/app/server.py" \
  --app-root "$SCRIPT_DIR" \
  scan-accounts \
  --instance "$INSTANCE_ID"
