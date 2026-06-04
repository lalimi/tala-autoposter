#!/usr/bin/env bash
# Install the macOS launchd agent for the SIGNAL REFRESHER (Vercel architecture).
#
# In the Vercel + Supabase setup, posting runs on Vercel. The Mac's only job is
# to scrape Threads (needs a browser) and push fresh signals to Supabase every
# 6h. This installs that periodic refresher.
#
# (The all-local poster plist com.tala.autoposter.plist is kept in deploy/ for
# the non-Vercel alternative — do NOT run both, or you'll double-post.)
set -euo pipefail

LABEL="com.tala.refresh"
APP_DIR="/Users/lalitamirosnicenko/tala-autoposter"
PLIST_SRC="$APP_DIR/deploy/$LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

case "${1:-install}" in
  install)
    mkdir -p "$HOME/Library/LaunchAgents" "$APP_DIR/logs"
    cp "$PLIST_SRC" "$PLIST_DST"
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    echo "✅ loaded $LABEL (refreshes signals now, then every 6h)"
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
