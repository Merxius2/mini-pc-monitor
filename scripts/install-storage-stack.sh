#!/usr/bin/env bash
# Samba + Transmission + ClamAV on /mnt/storage for Mini-PC Monitor dashboard.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MOUNT="/mnt/storage"
SECRETS_DIR="/etc/mini-pc-monitor"
RPC_PASS_FILE="$SECRETS_DIR/transmission-rpc-password"
SETTINGS_JSON="/var/lib/transmission-daemon/info/settings.json"
GROUP="storage-apps"

if [ ! -d "$MOUNT" ]; then
  echo "Mount $MOUNT not found. Run install-storage-raid.sh first."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y samba transmission-daemon clamav clamav-daemon clamav-freshclam

sudo groupadd -f "$GROUP"
sudo usermod -aG "$GROUP" "$USER"
sudo usermod -aG "$GROUP" debian-transmission 2>/dev/null || true
sudo usermod -aG "$GROUP" clamav 2>/dev/null || true

sudo mkdir -p \
  "$MOUNT/shared/Downloads" \
  "$MOUNT/downloads/incomplete" \
  "$MOUNT/torrents/watch" \
  "$MOUNT/quarantine" \
  "$MOUNT/logs"
sudo chown -R "$USER:$GROUP" "$MOUNT/shared" "$MOUNT/torrents" "$MOUNT/logs"
sudo chown -R debian-transmission:"$GROUP" "$MOUNT/shared/Downloads" "$MOUNT/downloads" "$MOUNT/quarantine"
sudo chmod -R g+rwX "$MOUNT/shared" "$MOUNT/downloads" "$MOUNT/torrents" "$MOUNT/quarantine" "$MOUNT/logs"
sudo chmod g+s "$MOUNT/shared/Downloads"

sudo cp "$ROOT/scripts/minipc-samba-admin" /usr/local/sbin/
sudo chmod 755 /usr/local/sbin/minipc-samba-admin
sudo cp "$ROOT/scripts/minipc-clamscan-download.sh" /usr/local/sbin/
sudo chmod 755 /usr/local/sbin/minipc-clamscan-download.sh
sudo cp "$ROOT/scripts/minipc-clamscan-admin" /usr/local/sbin/
sudo chmod 755 /usr/local/sbin/minipc-clamscan-admin
sudo cp "$ROOT/scripts/minipc-clamscan-lib.sh" /usr/local/sbin/
sudo chmod 644 /usr/local/sbin/minipc-clamscan-lib.sh

sudo mkdir -p /etc/samba/smb.d
sudo cp "$ROOT/scripts/samba-storage.conf" /etc/samba/smb.d/storage.conf
sudo sed -i '/include = \/etc\/samba\/smb.d/d' /etc/samba/smb.conf
if ! grep -q 'include = /etc/samba/smb.d/storage.conf' /etc/samba/smb.conf 2>/dev/null; then
  sudo sed -i '/^\[global\]/a \\   include = /etc/samba/smb.d/storage.conf' /etc/samba/smb.conf
fi

sudo mkdir -p "$SECRETS_DIR"
if [ ! -f "$RPC_PASS_FILE" ]; then
  openssl rand -base64 24 | tr -d '/+=' | head -c 24 | sudo tee "$RPC_PASS_FILE" >/dev/null
  sudo chmod 640 "$RPC_PASS_FILE"
  sudo chown root:"$USER" "$RPC_PASS_FILE"
fi
RPC_PASS="$(sudo cat "$RPC_PASS_FILE")"

sudo systemctl stop transmission-daemon.service 2>/dev/null || true
sudo mkdir -p /var/lib/transmission-daemon/info
sudo cp "$SETTINGS_JSON" "${SETTINGS_JSON}.bak.$(date +%s)" 2>/dev/null || true

sudo python3 <<PY
import json
from pathlib import Path

path = Path("$SETTINGS_JSON")
data = {}
if path.is_file():
    data = json.loads(path.read_text())
data.update({
    "download-dir": "$MOUNT/shared/Downloads",
    "incomplete-dir": "$MOUNT/downloads/incomplete",
    "watch-dir": "$MOUNT/torrents/watch",
    "umask": 2,
    "rpc-enabled": True,
    "rpc-bind-address": "127.0.0.1",
    "rpc-port": 9091,
    "rpc-authentication-required": True,
    "rpc-username": "transmission",
    "rpc-password": "$RPC_PASS",
    "rpc-whitelist-enabled": False,
    "script-torrent-done-enabled": True,
    "script-torrent-done-filename": "/usr/local/sbin/minipc-clamscan-download.sh",
})
path.write_text(json.dumps(data, indent=4))
PY

sudo chown debian-transmission:debian-transmission "$SETTINGS_JSON"
sudo chmod 600 "$SETTINGS_JSON"

sudo cp "$ROOT/scripts/minipc-monitor-sudoers" /etc/sudoers.d/mini-pc-monitor-storage
sudo chmod 440 /etc/sudoers.d/mini-pc-monitor-storage
if ! sudo visudo -cf /etc/sudoers.d/mini-pc-monitor-storage; then
  echo "Invalid sudoers fragment" >&2
  exit 1
fi

if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
  sudo ufw allow samba >/dev/null 2>&1 || sudo ufw allow 445/tcp comment 'Samba' >/dev/null 2>&1 || true
fi

sudo freshclam || true

CLAMD_CONF="/etc/clamav/clamd.conf"
if [ -f "$CLAMD_CONF" ]; then
  for key in MaxFileSize StreamMaxLength PCREMaxFileSize; do
    if grep -qE "^${key} " "$CLAMD_CONF"; then
      sudo sed -i "s/^${key} .*/${key} 4096M/" "$CLAMD_CONF"
    elif grep -qE "^#${key} " "$CLAMD_CONF"; then
      sudo sed -i "s/^#${key} .*/${key} 4096M/" "$CLAMD_CONF"
    else
      echo "${key} 4096M" | sudo tee -a "$CLAMD_CONF" >/dev/null
    fi
  done
fi

sudo mkdir -p /etc/apparmor.d/local
sudo cp "$ROOT/scripts/apparmor-transmission-daemon-local" /etc/apparmor.d/local/transmission-daemon
sudo cp "$ROOT/scripts/apparmor-clamd-local" /etc/apparmor.d/local/usr.sbin.clamd
if command -v apparmor_parser >/dev/null; then
  sudo apparmor_parser -r /etc/apparmor.d/transmission 2>/dev/null || true
  sudo apparmor_parser -r /etc/apparmor.d/usr.sbin.clamd 2>/dev/null || true
fi

sudo systemctl enable smbd nmbd transmission-daemon clamav-daemon clamav-freshclam
sudo systemctl restart smbd nmbd
sudo systemctl restart clamav-freshclam
sudo systemctl restart clamav-daemon
sudo systemctl restart transmission-daemon

echo "Storage stack installed."
echo "Samba: //$(hostname -I | awk '{print $1}')/storage"
echo "Transmission RPC password: $RPC_PASS_FILE (readable by $USER)"
echo "Dashboard: http://$(hostname -I | awk '{print $1}'):8080/storage"
