#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DEFAULT="/opt/projects/carbonet"
WORKSPACE="${FREEAGENT_WORKSPACE:-$WORKSPACE_DEFAULT}"

if [[ ! -d "$WORKSPACE" ]]; then
  echo "[ERROR] workspace not found: $WORKSPACE"
  echo "Set FREEAGENT_WORKSPACE to override."
  exit 1
fi

if [[ ! -x "$ROOT_DIR/.venv313/bin/python" ]]; then
  echo "[ERROR] .venv313/bin/python not found."
  echo "Run this once from Windows first: .\\.venv313\\Scripts\\python.exe START_FREEAGENT.py inspect"
  exit 1
fi

cd "$WORKSPACE"
echo "[INFO] FreeAgent (WSL) workspace: $WORKSPACE"
echo "[INFO] Running interactive console..."
exec "$ROOT_DIR/.venv313/bin/python" "$ROOT_DIR/freeagent_console.py" --interactive --workspace "$WORKSPACE"

