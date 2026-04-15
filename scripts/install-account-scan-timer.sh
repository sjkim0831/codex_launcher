#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
INSTANCE_ID="${1:-${CARBONET_INSTANCE_ID:-default}}"
INTERVAL_MIN="${CARBONET_ACCOUNT_SCAN_INTERVAL_MIN:-15}"

mkdir -p "$UNIT_DIR"

sed \
  -e "s|/opt/util/codex|$SCRIPT_DIR|g" \
  -e "s|\${CARBONET_INSTANCE_ID}|$INSTANCE_ID|g" \
  "$SCRIPT_DIR/systemd/carbonet-account-scan.service" >"$UNIT_DIR/carbonet-account-scan.service"

awk -v interval="$INTERVAL_MIN" '
  BEGIN { replaced = 0 }
  /^OnUnitActiveSec=/ { print "OnUnitActiveSec=" interval "m"; replaced = 1; next }
  { print }
' "$SCRIPT_DIR/systemd/carbonet-account-scan.timer" >"$UNIT_DIR/carbonet-account-scan.timer"

systemctl --user daemon-reload
systemctl --user enable --now carbonet-account-scan.timer
systemctl --user status carbonet-account-scan.timer --no-pager || true
