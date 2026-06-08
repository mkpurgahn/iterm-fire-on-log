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
#
# It runs for as long as iTerm2 is open -- no arbitrary time cap. When the
# animator can't connect (iTerm2 closed) it fails fast; after a short grace
# period of continuous fast failures we conclude iTerm2 is gone and exit
# cleanly so we don't spin forever (the AutoLaunch hook restarts us next time
# iTerm2 opens). A very long backstop guards against a truly stuck process.
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
BACKSTOP_SECONDS=$((30 * 24 * 3600))   # 30-day backstop, just in case
END=$(( $(date +%s) + BACKSTOP_SECONDS ))
FAST_FAIL_LIMIT=30                     # ~60s of "iTerm2 closed" before giving up
fails=0

echo "supervisor start $(date)" >> "$LOG"
while [ ! -f "$STOP" ] && [ "$(date +%s)" -lt "$END" ]; do
  run_start=$(date +%s)
  "$PYTHON" -u "$HERE/fire_on_log.py" dance --fps "$FPS" --minutes "$MINUTES" >> "$LOG" 2>&1 || true
  [ -f "$STOP" ] && break

  # A run shorter than 10s means the animator couldn't connect (iTerm2 closed).
  # A normal run lasts minutes (until the API socket drops), which resets fails.
  if [ $(( $(date +%s) - run_start )) -lt 10 ]; then
    fails=$((fails + 1))
  else
    fails=0
  fi
  if [ "$fails" -ge "$FAST_FAIL_LIMIT" ]; then
    echo "supervisor: iTerm2 appears closed ($fails fast failures) -- exiting" >> "$LOG"
    break
  fi
  sleep 2
done
"$PYTHON" "$HERE/fire_on_log.py" clear >> "$LOG" 2>&1 || true
rm -f "$STATE"
echo "supervisor end $(date)" >> "$LOG"
