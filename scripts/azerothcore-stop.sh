#!/bin/bash
# Stop AzerothCore game servers, Apache (player map), and MySQL.
set -euo pipefail

logger -t azerothcore-stop "Stopping game servers, Apache, and MySQL"

/usr/bin/tmux kill-server 2>/dev/null || true
pkill -x worldserver 2>/dev/null || true
pkill -x authserver 2>/dev/null || true

for _ in 1 2 3 4 5; do
  pgrep -x worldserver >/dev/null && sleep 1 && continue
  pgrep -x authserver >/dev/null && sleep 1 && continue
  break
done

# Apache player map holds MySQL connections — stop it before MySQL.
sudo -n systemctl stop apache2.service
# MySQL can take minutes to shut down cleanly; don't block the dashboard toggle.
sudo -n systemctl stop --no-block mysql.service
