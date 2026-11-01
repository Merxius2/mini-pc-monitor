#!/usr/bin/env bash
# Install and start the standalone video download web app on the mini-PC.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_NAME="video-download.service"
GROUP="storage-apps"

chmod +x "$ROOT/scripts/serve-video-download.sh"

DOWNLOAD_DIR="/mnt/storage/shared/Downloads/videos"
if [ -f "$ROOT/config/settings.yaml" ]; then
  parsed="$(python3 - <<'PY' "$ROOT/config/settings.yaml"
import sys
from pathlib import Path
try:
    import yaml
except ImportError:
    raise SystemExit(0)
data = yaml.safe_load(Path(sys.argv[1]).read_text(encoding="utf-8")) or {}
print((data.get("video_download") or {}).get("download_dir") or "")
PY
  )"
  if [ -n "$parsed" ]; then
    DOWNLOAD_DIR="$parsed"
  fi
fi

if mountpoint -q /mnt/storage 2>/dev/null; then
  sudo mkdir -p "$DOWNLOAD_DIR"
  sudo groupadd -f "$GROUP" 2>/dev/null || true
  sudo chown "$USER:$GROUP" "$DOWNLOAD_DIR"
  sudo chmod 2775 "$DOWNLOAD_DIR"
else
  echo "Warning: /mnt/storage not mounted — create $DOWNLOAD_DIR after RAID is up" >&2
fi

sudo cp "$ROOT/scripts/video-download.service" "/etc/systemd/system/$SERVICE_NAME"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

if command -v ufw >/dev/null 2>&1 && sudo ufw status 2>/dev/null | grep -q "Status: active"; then
  sudo ufw allow 8083/tcp comment 'Video download tool' || true
fi

echo "video-download: $(systemctl is-active "$SERVICE_NAME")"
echo "Downloads: $DOWNLOAD_DIR"
echo "Open http://192.168.1.30:8083/ (or video_download.public_url in settings.yaml)"
