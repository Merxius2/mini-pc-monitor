#!/usr/bin/env bash
# Install Domoticz (Docker) with RFLink USB on port 8082.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DZ_DIR="${HOME}/domoticz"
RFLINK_ID="${RFLINK_DEVICE:-/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0}"

if [[ ! -e "$RFLINK_ID" ]]; then
  echo "RFLink USB serial not found at: $RFLINK_ID"
  echo "Plug in the Arduino and run: ls -la /dev/serial/by-id/"
  exit 1
fi

if ! command -v docker >/dev/null; then
  echo "Docker is required."
  exit 1
fi

mkdir -p "$DZ_DIR/userdata"
cp "$ROOT/domoticz/docker-compose.yml" "$DZ_DIR/"

sudo cp "$ROOT/scripts/domoticz.service" /etc/systemd/system/domoticz.service
sudo sed -i "s|RFLINK_DEVICE=.*|RFLINK_DEVICE=$RFLINK_ID|" /etc/systemd/system/domoticz.service
sudo systemctl daemon-reload
sudo systemctl enable domoticz.service

if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow 8082/tcp comment "Domoticz" >/dev/null 2>&1 || true
fi

echo ""
echo "RFLink USB is mapped to Domoticz (/dev/ttyUSB0 in container)."
echo "Stop Home Assistant before starting Domoticz if HA still mounts the same USB."
echo ""
echo "  UI: http://$(hostname -I | awk '{print $1}'):8082"
echo "  In Domoticz: Setup → Hardware → RFLink USB → /dev/ttyUSB0"
echo ""
echo "Start with: sudo systemctl start domoticz.service"
