#!/usr/bin/env bash
# Persist mdadm RAID1 + /mnt/storage for boot and resume from suspend.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -f /etc/mdadm/mdadm.conf ] || ! grep -q '/dev/md0' /etc/mdadm/mdadm.conf; then
  echo "No /dev/md0 entry in /etc/mdadm/mdadm.conf — create the array first."
  exit 1
fi

sudo cp "$ROOT/scripts/minipc-mdadm-lib.sh" /usr/local/sbin/
sudo chmod 644 /usr/local/sbin/minipc-mdadm-lib.sh
sudo cp "$ROOT/scripts/minipc-ensure-storage.sh" /usr/local/sbin/
sudo chmod 755 /usr/local/sbin/minipc-ensure-storage.sh
sudo cp "$ROOT/scripts/minipc-mdadm-sync-conf.sh" /usr/local/sbin/
sudo chmod 755 /usr/local/sbin/minipc-mdadm-sync-conf.sh
sudo /usr/local/sbin/minipc-mdadm-sync-conf.sh || true

sudo cp "$ROOT/scripts/minipc-storage.service" /etc/systemd/system/minipc-storage.service
sudo cp "$ROOT/scripts/minipc-storage-sleep" /usr/lib/systemd/system-sleep/minipc-storage
sudo chmod 755 /usr/lib/systemd/system-sleep/minipc-storage

# Storage is mounted by minipc-storage after multi-user boot — not during local-fs.
if grep -q '/mnt/storage' /etc/fstab; then
  if ! grep '/mnt/storage' /etc/fstab | grep -q noauto; then
    sudo sed -i 's|\(/mnt/storage[[:space:]]\+[^[:space:]]\+[[:space:]]\+\)\([^[:space:]]*\)|\1noauto,\2|' /etc/fstab
  fi
  if ! grep '/mnt/storage' /etc/fstab | grep -q nofail; then
    sudo sed -i 's|\(/mnt/storage[[:space:]]\+[^[:space:]]\+[[:space:]]\+\)\([^[:space:]]*\)|\1\2,nofail,x-systemd.device-timeout=30|' /etc/fstab
  fi
fi

for unit in smbd.service transmission-daemon.service; do
  dropin="/etc/systemd/system/${unit}.d"
  sudo mkdir -p "$dropin"
  case "$unit" in
    smbd.service)
      sudo cp "$ROOT/scripts/minipc-smbd-after-storage.conf" "$dropin/minipc-after-storage.conf"
      ;;
    transmission-daemon.service)
      sudo cp "$ROOT/scripts/minipc-transmission-after-storage.conf" "$dropin/minipc-after-storage.conf"
      ;;
  esac
done

sudo rm -f /etc/systemd/system/local-fs.target.wants/minipc-storage.service
sudo systemctl disable minipc-storage.service 2>/dev/null || true
sudo systemctl daemon-reload
sudo systemctl enable minipc-storage.service

sudo update-initramfs -u

echo "Enabled minipc-storage.service (after multi-user boot) and systemd sleep hook (resume)."
