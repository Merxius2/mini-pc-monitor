#!/usr/bin/env bash
# Install and start the dashboard systemd service on the mini-PC.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="mini-pc-monitor.service"

chmod +x "$ROOT/scripts/serve-dashboard.sh" "$ROOT/scripts/pull-on-mini-pc.sh" "$ROOT/scripts/check-and-deploy.sh"

if [[ ! -x "$ROOT/.venv/bin/uvicorn" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
fi

sudo cp "$ROOT/scripts/mini-pc-monitor.service" "/etc/systemd/system/$SERVICE_NAME"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow 8080/tcp comment 'Mini-PC Monitor dashboard' || true
fi

echo "Dashboard service status:"
systemctl is-active "$SERVICE_NAME"
systemctl status "$SERVICE_NAME" --no-pager -l | head -15
echo
echo "Open from your Mac: http://$(hostname -I | awk '{print $1}'):8080/"
