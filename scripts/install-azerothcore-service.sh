#!/usr/bin/env bash
# Install AzerothCore systemd unit and stop script on the mini-PC.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

sudo cp "$ROOT/scripts/azerothcore-stop.sh" /usr/local/sbin/
sudo chmod 755 /usr/local/sbin/azerothcore-stop.sh
sudo cp "$ROOT/scripts/azerothcore.service" /etc/systemd/system/azerothcore.service

sudo systemctl daemon-reload
sudo systemctl enable azerothcore.service

echo "AzerothCore service installed (not started)."
echo "Start from the dashboard toggle or: sudo systemctl start azerothcore.service"
systemctl cat azerothcore.service --no-pager | head -20
