#!/bin/bash
# Assemble mdadm arrays and mount /mnt/storage (boot + after suspend/resume).
set -euo pipefail

MOUNT="/mnt/storage"
FSTAB_UUID="c28fde15-51ba-4db3-a923-17898148f384"

if ! command -v mdadm >/dev/null; then
  exit 0
fi

mdadm --assemble --scan >/dev/null 2>&1 || true

if [ -b /dev/md0 ]; then
  mdadm --wait /dev/md0 --action=idle 2>/dev/null || true
fi

if mountpoint -q "$MOUNT"; then
  exit 0
fi

if grep -q "$FSTAB_UUID" /etc/fstab 2>/dev/null; then
  mount "$MOUNT"
else
  # Fallback if fstab was edited but UUID unchanged on md0
  mount -U "$FSTAB_UUID" "$MOUNT" 2>/dev/null || mount /dev/md0 "$MOUNT"
fi
