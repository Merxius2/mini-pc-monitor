#!/usr/bin/env bash
# Install AzerothCore systemd units on the mini-PC.
# Edit paths in the unit files if your AzerothCore install lives elsewhere.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for unit in azerothcore-authserver.service azerothcore-worldserver.service azerothcore.target; do
  sudo cp "$ROOT/scripts/$unit" "/etc/systemd/system/$unit"
done

sudo systemctl daemon-reload
sudo systemctl enable azerothcore.target

echo "AzerothCore units installed (not started)."
echo "Start from the dashboard toggle or: sudo systemctl start azerothcore.target"
systemctl list-unit-files 'azerothcore*' --no-pager
