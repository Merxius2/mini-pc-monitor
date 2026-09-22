#!/usr/bin/env bash
# Install systemd timer: auto pull + restart dashboard when main changes.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

chmod +x "$ROOT/scripts/check-and-deploy.sh" "$ROOT/scripts/pull-on-mini-pc.sh"

sudo cp "$ROOT/scripts/mini-pc-monitor-deploy.service" /etc/systemd/system/
sudo cp "$ROOT/scripts/mini-pc-monitor-deploy.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mini-pc-monitor-deploy.timer
sudo systemctl start mini-pc-monitor-deploy.timer

echo "Deploy trigger timer:"
systemctl is-active mini-pc-monitor-deploy.timer
systemctl list-timers mini-pc-monitor-deploy.timer --no-pager
