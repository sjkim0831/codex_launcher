#!/usr/bin/env bash
set -euo pipefail

nohup /opt/util/codex/bin/carbonet-codex >/tmp/carbonet-codex.log 2>&1 &
