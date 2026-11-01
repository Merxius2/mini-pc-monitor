#!/bin/bash
# Assemble mdadm arrays and mount /mnt/storage (boot + after suspend/resume).
set -euo pipefail

MOUNT="/mnt/storage"
MD_DEV="/dev/md0"
FSTAB_UUID="c28fde15-51ba-4db3-a923-17898148f384"
MDADM_CONF="/etc/mdadm/mdadm.conf"

if ! command -v mdadm >/dev/null; then
  exit 0
fi

array_uuid() {
  if [ -f "$MDADM_CONF" ]; then
    grep -oE 'UUID=[0-9a-f:]+' "$MDADM_CONF" | head -1 | cut -d= -f2
  fi
}

md0_broken() {
  grep -q "^md0.*: broken" /proc/mdstat 2>/dev/null
}

md0_member_disks() {
  local uuid="$1"
  local d
  for d in /dev/disk/by-id/ata-* /dev/sd?; do
    [ -e "$d" ] || continue
    if mdadm --examine "$d" 2>/dev/null | grep -q "Array UUID : $uuid"; then
      readlink -f "$d"
    fi
  done | sort -u
}

assemble_md0() {
  local uuid
  uuid="$(array_uuid)"
  if md0_broken; then
    mdadm --stop "$MD_DEV" >/dev/null 2>&1 || true
  fi
  if [ ! -b "$MD_DEV" ]; then
    if [ -n "${uuid:-}" ]; then
      mdadm --assemble --uuid="$uuid" "$MD_DEV" >/dev/null 2>&1 || true
    fi
    mdadm --assemble --scan >/dev/null 2>&1 || true
  fi
  if md0_broken && [ -n "${uuid:-}" ]; then
    mdadm --stop "$MD_DEV" >/dev/null 2>&1 || true
    mapfile -t members < <(md0_member_disks "$uuid")
    if [ "${#members[@]}" -ge 2 ]; then
      mdadm --assemble --uuid="$uuid" "$MD_DEV" "${members[@]}" >/dev/null 2>&1 || true
    else
      mdadm --assemble --uuid="$uuid" "$MD_DEV" >/dev/null 2>&1 || true
    fi
  fi
}

storage_mounted_readonly() {
  mountpoint -q "$MOUNT" || return 1
  findmnt -no OPTIONS "$MOUNT" 2>/dev/null | grep -qE '(^|,)(ro|emergency_ro)(,|$)'
}

assemble_md0

if [ -b "$MD_DEV" ]; then
  mdadm --wait "$MD_DEV" --action=idle 2>/dev/null || true
fi

if storage_mounted_readonly; then
  uuid="$(array_uuid)"
  if md0_broken && [ -n "${uuid:-}" ]; then
    systemctl stop smbd nmbd transmission-daemon video-download.service 2>/dev/null || true
    umount "$MOUNT" 2>/dev/null || umount -l "$MOUNT" 2>/dev/null || true
    mdadm --stop "$MD_DEV" 2>/dev/null || true
    mapfile -t members < <(md0_member_disks "$uuid")
    if [ "${#members[@]}" -ge 2 ]; then
      mdadm --assemble --uuid="$uuid" "$MD_DEV" "${members[@]}"
    fi
    fsck -y -f "$MD_DEV" || fsck -y "$MD_DEV" || true
  fi
fi

if mountpoint -q "$MOUNT"; then
  if storage_mounted_readonly; then
    mount -o remount,rw "$MOUNT" 2>/dev/null || true
  fi
  exit 0
fi

if grep -q "$FSTAB_UUID" /etc/fstab 2>/dev/null; then
  mount "$MOUNT"
else
  mount -U "$FSTAB_UUID" "$MOUNT" 2>/dev/null || mount "$MD_DEV" "$MOUNT"
fi
