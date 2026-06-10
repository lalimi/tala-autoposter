#!/usr/bin/env bash
# One-shot VPS installer (Ubuntu/Debian, e.g. Hetzner). Run as root from the repo:
#   sudo bash deploy/vps-setup.sh
#
# Sets up a venv, installs deps + a headless Chromium (for the scraper), and
# installs+enables systemd timers for: tala posts, blacksea posts, tala
# comments, and the 3-hourly signal/comment-target scrape.
#
# Prereq: cp .env.example .env and fill the keys FIRST (ANTHROPIC_API_KEY,
# SUPABASE_URL, SUPABASE_SERVICE_KEY, THREADS_ACCESS_TOKEN,
# BLACKSEA_THREADS_ACCESS_TOKEN). Posting works without the scraper; commenting
# needs a logged-in session at parser/scout_session.json (scp it from your Mac).
set -euo pipefail

APP="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP"
echo "==> app dir: $APP"

if [ "$(id -u)" -ne 0 ]; then
  echo "run as root: sudo bash deploy/vps-setup.sh" >&2; exit 1
fi
if [ ! -f "$APP/.env" ]; then
  echo "missing $APP/.env — copy .env.example to .env and fill the keys first." >&2
  exit 1
fi

echo "==> system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git ca-certificates >/dev/null

echo "==> python venv + deps"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt -r requirements-scraper.txt

echo "==> headless chromium for the scraper (installs OS libs too)"
.venv/bin/python -m playwright install --with-deps chromium

# Running as root -> Playwright needs --no-sandbox; scraper honours this env.
grep -q '^PLAYWRIGHT_NO_SANDBOX=' .env || echo 'PLAYWRIGHT_NO_SANDBOX=1' >> .env

echo "==> installing systemd units"
sed "s#__APP__#$APP#g" deploy/systemd/tala@.service > /etc/systemd/system/tala@.service
cp deploy/systemd/tala@*.timer /etc/systemd/system/
chmod +x deploy/systemd/run-job.sh
systemctl daemon-reload

echo "==> enabling timers"
for t in post-tala post-blacksea comment-tala refresh; do
  systemctl enable --now "tala@$t.timer"
done

echo
echo "==> done. timer status:"
systemctl list-timers 'tala@*' --no-pager || true
echo
echo "Smoke-test one tick now (publishes for real):"
echo "  sudo -E .venv/bin/python main.py --brand tala --publish"
echo "Preview a comment without posting (needs a scraped queue):"
echo "  sudo -E .venv/bin/python main.py --brand tala --comment --dry-run"
echo "Logs:  journalctl -u 'tala@*' -f"
