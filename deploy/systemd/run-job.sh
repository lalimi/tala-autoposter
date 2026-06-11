#!/usr/bin/env bash
# Maps a systemd instance name (tala@<job>) to a main.py invocation.
# Self-locating: works wherever the repo is cloned. Used by tala@.service.
set -euo pipefail

# repo root = two levels up from deploy/systemd/
APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$APP"
PY="$APP/.venv/bin/python"

case "${1:-}" in
  post-tala)      exec "$PY" main.py --brand tala     --tick ;;
  post-blacksea)  exec "$PY" main.py --brand blacksea --tick ;;
  comment-tala)   exec "$PY" main.py --brand tala     --comment --tick ;;
  refresh)          exec "$PY" -m scripts.refresh_signals ;;
  metrics-tala)     exec "$PY" main.py --brand tala     --metrics ;;
  metrics-blacksea) exec "$PY" main.py --brand blacksea --metrics ;;
  update)
    # Pull code, then re-sync systemd units so unit/timer changes (and brand-new
    # timers) self-apply too — no manual reinstall ever needed.
    git -C "$APP" pull --ff-only --quiet || true
    if [ -d /etc/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
      sed "s#__APP__#$APP#g" "$APP/deploy/systemd/tala@.service" \
        > /etc/systemd/system/tala@.service 2>/dev/null || true
      cp "$APP"/deploy/systemd/tala@*.timer /etc/systemd/system/ 2>/dev/null || true
      systemctl daemon-reload 2>/dev/null || true
      for t in post-tala post-blacksea comment-tala metrics-tala metrics-blacksea refresh update; do
        systemctl enable --now "tala@$t.timer" >/dev/null 2>&1 || true
      done
    fi
    ;;
  *) echo "unknown job: '${1:-}' (post-tala|post-blacksea|comment-tala|metrics-tala|metrics-blacksea|refresh|update)" >&2
     exit 2 ;;
esac
