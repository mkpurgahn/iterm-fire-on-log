#!/bin/bash
# Idempotent launcher, meant to be invoked by the iTerm2 AutoLaunch script on
# every iTerm2 startup. If a supervisor is already running it does nothing (so
# you never get two animators fighting over the background); otherwise it starts
# the supervisor detached. The supervisor retries the iTerm2 API connection in a
# loop, so it's fine if the API isn't ready the instant iTerm2 launches.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if pgrep -f "$HERE/run.sh" >/dev/null 2>&1; then
  exit 0
fi

rm -f "${FIRE_ON_LOG_HOME:-$HOME/.fire-on-log}/STOP"
nohup "$HERE/run.sh" >/dev/null 2>&1 &
disown 2>/dev/null || true
exit 0
