#!/bin/bash
# Supervisor: keeps the fire-on-log animation running across iTerm2 API
# connection drops (the Python API socket dies cleanly every few minutes).
# Stop with:  touch "$FIRE_ON_LOG_HOME/STOP"   (default ~/.fire-on-log/STOP)
#
# Config via env:
#   PYTHON            python to use (default ./venv/bin/python next to this file)
#   FIRE_ON_LOG_HOME  runtime dir for cache/state/logs (default ~/.fire-on-log)
#   FIRE_GIF          source GIF (default $FIRE_ON_LOG_HOME/fire.gif)
#   FPS, MINUTES      animation speed / per-run length
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$HERE/venv/bin/python}"
export FIRE_ON_LOG_HOME="${FIRE_ON_LOG_HOME:-$HOME/.fire-on-log}"
FPS="${FPS:-16}"
MINUTES="${MINUTES:-60}"

mkdir -p "$FIRE_ON_LOG_HOME"
LOG="$FIRE_ON_LOG_HOME/dance.log"
STOP="$FIRE_ON_LOG_HOME/STOP"
STATE="$FIRE_ON_LOG_HOME/frame_idx"

rm -f "$STOP" "$STATE"
MAX_SECONDS=$((24 * 3600))    # safety cap: 24 hours
END=$(( $(date +%s) + MAX_SECONDS ))
echo "supervisor start $(date)" >> "$LOG"
while [ ! -f "$STOP" ] && [ "$(date +%s)" -lt "$END" ]; do
  "$PYTHON" -u "$HERE/fire_on_log.py" dance --fps "$FPS" --minutes "$MINUTES" >> "$LOG" 2>&1 || true
  [ -f "$STOP" ] && break
  sleep 0.4
done
"$PYTHON" "$HERE/fire_on_log.py" clear >> "$LOG" 2>&1 || true
rm -f "$STATE"
echo "supervisor end $(date)" >> "$LOG"
