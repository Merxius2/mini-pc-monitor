#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

sudo cp "$ROOT/scripts/minipc-system-update" /usr/local/sbin/
sudo chmod 755 /usr/local/sbin/minipc-system-update

SUDOERS="/etc/sudoers.d/mini-pc-monitor-system-updates"
sudo tee "$SUDOERS" >/dev/null <<'EOF'
# Mini-PC Monitor — apt status / upgrade
sylvester ALL=(ALL) NOPASSWD: /usr/local/sbin/minipc-system-update status
sylvester ALL=(ALL) NOPASSWD: /usr/local/sbin/minipc-system-update refresh
sylvester ALL=(ALL) NOPASSWD: /usr/local/sbin/minipc-system-update upgrade
EOF
sudo chmod 440 "$SUDOERS"
sudo visudo -cf "$SUDOERS"

echo "System update helper installed."
