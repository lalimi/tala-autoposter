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
  refresh)        exec "$PY" -m scripts.refresh_signals ;;
  update)         exec git -C "$APP" pull --ff-only --quiet ;;
  *) echo "unknown job: '${1:-}' (use post-tala|post-blacksea|comment-tala|refresh|update)" >&2
     exit 2 ;;
esac
