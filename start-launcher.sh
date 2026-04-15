#!/bin/bash
cd /opt/util/codex
nohup python3 -m app.server --app-root /opt/util/codex serve --host 0.0.0.0 --port 43110 > /tmp/codex-launcher.log 2>&1 &
echo "Launcher started (PID: $!)"
sleep 2
cat /tmp/codex-launcher.log
