#!/usr/bin/env bash
set -euo pipefail

UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

systemctl --user disable --now carbonet-account-scan.timer || true
rm -f "$UNIT_DIR/carbonet-account-scan.service" "$UNIT_DIR/carbonet-account-scan.timer"
systemctl --user daemon-reload || true
