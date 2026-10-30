#!/usr/bin/env bash
# Install Home Assistant (Docker) + RFLink serial gateway on the mini PC.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HA_DIR="${HOME}/homeassistant"
RFLINK_ID="${RFLINK_DEVICE:-/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0}"

if [[ ! -e "$RFLINK_ID" ]]; then
  echo "RFLink USB serial not found at: $RFLINK_ID"
  echo "Plug in the Arduino and run: ls -la /dev/serial/by-id/"
  exit 1
fi

if ! command -v docker >/dev/null; then
  echo "Docker is required. Install with: curl -fsSL https://get.docker.com | sudo sh"
  exit 1
fi

sudo usermod -aG docker "$USER" 2>/dev/null || true

mkdir -p "$HA_DIR/config"
cp "$ROOT/homeassistant/docker-compose.yml" "$HA_DIR/"
if [[ ! -f "$HA_DIR/config/.storage/core.config" ]]; then
  cp "$ROOT/homeassistant/config/configuration.yaml" "$HA_DIR/config/configuration.yaml"
else
  echo "Keeping existing $HA_DIR/config (already onboarded)."
fi

sudo cp "$ROOT/scripts/homeassistant.service" /etc/systemd/system/homeassistant.service
sudo sed -i "s|RFLINK_DEVICE=.*|RFLINK_DEVICE=$RFLINK_ID|" /etc/systemd/system/homeassistant.service
sudo systemctl daemon-reload
sudo systemctl enable homeassistant.service
sudo systemctl restart homeassistant.service

if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow 8123/tcp comment "Home Assistant" >/dev/null 2>&1 || true
fi

echo ""
echo "Home Assistant starting (first pull can take several minutes)."
echo "  UI: http://$(hostname -I | awk '{print $1}'):8123"
echo "  RFLink: $RFLINK_ID → /dev/rflink in container"
echo ""
echo "433 MHz sockets: press the physical remote once, then find the new entity under"
echo "Developer Tools → States. Configure as switch — see homeassistant/config/configuration.yaml"
