#!/usr/bin/env bash
# Install the tala-autoposter as a macOS launchd LaunchAgent.
# Runs python main.py (the scheduler) in the background, restarts on crash,
# starts again at every login. First auto-post is one interval after load;
# use `python main.py --publish` to post on demand.
set -euo pipefail

LABEL="com.tala.autoposter"
APP_DIR="/Users/lalitamirosnicenko/tala-autoposter"
PLIST_SRC="$APP_DIR/deploy/$LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

case "${1:-install}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" "$APP_DIR/logs"
    cp "$PLIST_SRC" "$PLIST_DST"
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    echo "✅ loaded $LABEL"
    launchctl list | grep "$LABEL" || true
    ;;
  uninstall)
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    rm -f "$PLIST_DST"
    echo "🗑️  unloaded and removed $LABEL"
    ;;
  status)
    launchctl list | grep "$LABEL" || echo "not loaded"
    ;;
  *)
    echo "usage: $0 [install|uninstall|status]"; exit 1 ;;
esac
