#!/bin/bash
# Assemble mdadm arrays and mount /mnt/storage (boot + after suspend/resume).
# Uses /dev/disk/by-id only so sdX letter swaps do not break RAID1 assembly.
set -euo pipefail

MOUNT="/mnt/storage"
MD_DEV="/dev/md0"
FSTAB_UUID="c28fde15-51ba-4db3-a923-17898148f384"
MDADM_CONF="/etc/mdadm/mdadm.conf"
LIB="/usr/local/sbin/minipc-mdadm-lib.sh"

# shellcheck source=/dev/null
[ -f "$LIB" ] && . "$LIB"

if ! command -v mdadm >/dev/null; then
  exit 0
fi

array_uuid() {
  minipc_md_array_uuid "$MDADM_CONF"
}

md0_broken() {
  grep -qE '^md0[[:space:]]*:[[:space:]]*active.*broken' /proc/mdstat 2>/dev/null \
    || grep -qE '^md0[[:space:]]*:[[:space:]]*broken' /proc/mdstat 2>/dev/null
}

md0_active() {
  grep -qE '^md0[[:space:]]*:' /proc/mdstat 2>/dev/null
}

wait_for_members() {
  local uuid="$1"
  local want="${2:-2}"
  local attempt found_count
  for attempt in $(seq 1 45); do
    udevadm settle 2>/dev/null || true
    mapfile -t _found < <(minipc_md_member_by_id "$uuid")
    found_count="${#_found[@]}"
    if [ "$found_count" -ge "$want" ]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

sync_mdadm_conf() {
  local uuid="$1"
  shift
  local members=("$@")
  if [ -z "${uuid:-}" ] || [ "${#members[@]}" -lt 1 ]; then
    return 0
  fi
  minipc_md_write_conf "$MD_DEV" "$uuid" "${members[@]}"
}

minipc_md_stop_for_reassemble() {
  systemctl stop smbd nmbd transmission-daemon 2>/dev/null || true
  if mountpoint -q "$MOUNT"; then
    umount "$MOUNT" 2>/dev/null || umount -l "$MOUNT" 2>/dev/null || true
  fi
  mdadm --stop "$MD_DEV" >/dev/null 2>&1 || true
}

assemble_md0() {
  local uuid members=()
  uuid="$(array_uuid)"
  if [ -z "${uuid:-}" ]; then
    mdadm --assemble --scan >/dev/null 2>&1 || true
    return 0
  fi

  udevadm settle 2>/dev/null || true
  wait_for_members "$uuid" 2 || wait_for_members "$uuid" 1 || true
  mapfile -t members < <(minipc_md_member_by_id "$uuid")
  sync_mdadm_conf "$uuid" "${members[@]}"

  if md0_active && ! md0_broken; then
    return 0
  fi

  if md0_broken || md0_active; then
    minipc_md_stop_for_reassemble
  fi

  if [ "${#members[@]}" -ge 2 ]; then
    mdadm --assemble --uuid="$uuid" "$MD_DEV" "${members[@]}" >/dev/null 2>&1 || true
  elif [ "${#members[@]}" -eq 1 ]; then
    mdadm --assemble --uuid="$uuid" "$MD_DEV" "${members[0]}" >/dev/null 2>&1 || true
  else
    mdadm --assemble --uuid="$uuid" "$MD_DEV" >/dev/null 2>&1 || true
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
    mapfile -t members < <(minipc_md_member_by_id "$uuid")
    sync_mdadm_conf "$uuid" "${members[@]}"
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
