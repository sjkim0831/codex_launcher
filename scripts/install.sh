#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-/opt/util/codex}"

mkdir -p "$TARGET_DIR"
cp -R "$SOURCE_DIR/." "$TARGET_DIR/"
chmod +x "$TARGET_DIR/bin/carbonet-codex"
chmod +x "$TARGET_DIR/bin/carbonet-codex-watch"
chmod +x "$TARGET_DIR/scripts/install.sh"
chmod +x "$TARGET_DIR/scripts/account-scan.sh"
chmod +x "$TARGET_DIR/scripts/account-scan-loop.sh"
chmod +x "$TARGET_DIR/scripts/install-account-scan-timer.sh"
chmod +x "$TARGET_DIR/scripts/uninstall-account-scan-timer.sh"

echo "Installed Carbonet Codex Launcher to $TARGET_DIR"
