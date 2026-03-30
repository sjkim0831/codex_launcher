#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${1:-/opt/util/codex}"

mkdir -p "$TARGET_DIR"
cp -R "$SOURCE_DIR/." "$TARGET_DIR/"
chmod +x "$TARGET_DIR/bin/carbonet-codex"
chmod +x "$TARGET_DIR/scripts/install.sh"

echo "Installed Carbonet Codex Launcher to $TARGET_DIR"
