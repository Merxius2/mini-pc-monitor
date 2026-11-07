#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

sudo install -m 755 "$ROOT/scripts/minipc-restore-services" /usr/local/sbin/minipc-restore-services
sudo cp "$ROOT/scripts/minipc-restore-services.service" /etc/systemd/system/
sudo mkdir -p /var/lib/mini-pc-monitor
sudo chown sylvester:sylvester /var/lib/mini-pc-monitor 2>/dev/null || true

sudo systemctl daemon-reload
sudo systemctl enable minipc-restore-services.service

echo "Enabled minipc-restore-services.service (after minipc-storage on boot)."
