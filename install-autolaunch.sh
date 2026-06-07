#!/bin/bash
# Install (or update) the iTerm2 AutoLaunch hook so the animation starts
# automatically whenever iTerm2 launches.
#
# iTerm2 runs any script in its AutoLaunch folder at startup. We drop a tiny
# compiled AppleScript there that shells out to autostart.sh (the idempotent
# launcher next to this file).
#
# Run once:   ./install-autolaunch.sh
# Uninstall:  rm "~/Library/Application Support/iTerm2/Scripts/AutoLaunch/fire_on_log.scpt"
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTOLAUNCH="$HOME/Library/Application Support/iTerm2/Scripts/AutoLaunch"

mkdir -p "$AUTOLAUNCH"
osacompile -o "$AUTOLAUNCH/fire_on_log.scpt" \
  -e "do shell script \"$HERE/autostart.sh\""

echo "Installed iTerm2 AutoLaunch hook:"
echo "  $AUTOLAUNCH/fire_on_log.scpt  ->  $HERE/autostart.sh"
echo
echo "It will start on the next iTerm2 launch. To start it now without"
echo "restarting iTerm2, run:  $HERE/autostart.sh"
