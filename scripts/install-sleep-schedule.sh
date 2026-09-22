#!/usr/bin/env bash
# Install mini-PC sleep schedule systemd units and suspend script.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

sudo cp "$ROOT/scripts/minipc-poweroff-until-morning.sh" /usr/local/sbin/
sudo chmod 755 /usr/local/sbin/minipc-poweroff-until-morning.sh

for unit in minipc-nightly-off.service minipc-nightly-off.timer minipc-keep-awake.service minipc-keep-awake.timer; do
  sudo cp "$ROOT/scripts/$unit" "/etc/systemd/system/$unit"
done

sudo systemctl daemon-reload
sudo systemctl enable minipc-nightly-off.timer minipc-keep-awake.timer
sudo systemctl start minipc-nightly-off.timer minipc-keep-awake.timer

echo "Sleep schedule timers:"
systemctl list-timers minipc-nightly-off.timer minipc-keep-awake.timer --no-pager
