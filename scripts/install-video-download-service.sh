#!/usr/bin/env bash
# Install and start the standalone video download web app on the mini-PC.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="video-download.service"

chmod +x "$ROOT/scripts/serve-video-download.sh"

sudo cp "$ROOT/scripts/video-download.service" "/etc/systemd/system/$SERVICE_NAME"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

if command -v ufw >/dev/null 2>&1 && sudo ufw status 2>/dev/null | grep -q "Status: active"; then
  sudo ufw allow 8083/tcp comment 'Video download tool' || true
fi

echo "video-download: $(systemctl is-active "$SERVICE_NAME")"
echo "Open http://192.168.1.30:8083/ (or video_download.public_url in settings.yaml)"
