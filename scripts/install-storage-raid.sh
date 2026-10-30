#!/usr/bin/env bash
# Persist mdadm RAID1 + /mnt/storage for boot and resume from suspend.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ ! -f /etc/mdadm/mdadm.conf ] || ! grep -q '/dev/md0' /etc/mdadm/mdadm.conf; then
  echo "No /dev/md0 entry in /etc/mdadm/mdadm.conf — create the array first."
  exit 1
fi

sudo cp "$ROOT/scripts/minipc-ensure-storage.sh" /usr/local/sbin/
sudo chmod 755 /usr/local/sbin/minipc-ensure-storage.sh

sudo cp "$ROOT/scripts/minipc-storage.service" /etc/systemd/system/minipc-storage.service
sudo cp "$ROOT/scripts/minipc-storage-sleep" /usr/lib/systemd/system-sleep/minipc-storage
sudo chmod 755 /usr/lib/systemd/system-sleep/minipc-storage

# Reliable local mount at boot (not optional/nofail).
if grep -q '/mnt/storage' /etc/fstab; then
  sudo sed -i 's|/mnt/storage ext4 defaults,nofail|/mnt/storage ext4 defaults,noatime|' /etc/fstab
  sudo sed -i 's|/mnt/storage ext4 defaults |/mnt/storage ext4 defaults,noatime |' /etc/fstab
fi

sudo systemctl daemon-reload
sudo systemctl enable minipc-storage.service

sudo update-initramfs -u

echo "Enabled minipc-storage.service (boot) and systemd sleep hook (resume)."
