#!/usr/bin/env bash
# Run on the mini-PC: pull latest main and restart dashboard.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== git pull ==="
git fetch origin
git pull --ff-only origin main
echo "At commit: $(git log -1 --oneline)"

if [[ -x "$ROOT/.venv/bin/pip" ]]; then
  echo "=== pip install ==="
  "$ROOT/.venv/bin/pip" install -q -r requirements.txt
fi

echo "=== restart services ==="
if systemctl list-unit-files mini-pc-monitor.service &>/dev/null \
   && systemctl is-enabled mini-pc-monitor.service &>/dev/null; then
  sudo systemctl restart mini-pc-monitor
  echo "mini-pc-monitor: $(systemctl is-active mini-pc-monitor)"
else
  echo "mini-pc-monitor.service not installed — run install-dashboard-service.sh once"
fi

echo "Done."
