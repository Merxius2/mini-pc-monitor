#!/bin/bash
# Refresh mdadm drop-in with current /dev/disk/by-id RAID members (run after disk order changes).
set -euo pipefail

LIB="/usr/local/sbin/minipc-mdadm-lib.sh"
# shellcheck source=/dev/null
[ -f "$LIB" ] && . "$LIB"

MD_DEV="${MINIPC_MD_DEV:-/dev/md0}"
MDADM_CONF="${MINIPC_MDADM_CONF:-/etc/mdadm/mdadm.conf}"

if ! command -v mdadm >/dev/null; then
  echo "mdadm not installed" >&2
  exit 1
fi

uuid="$(minipc_md_array_uuid "$MDADM_CONF")"
if [ -z "${uuid:-}" ]; then
  echo "No ARRAY UUID in $MDADM_CONF" >&2
  exit 1
fi

udevadm settle 2>/dev/null || true
mapfile -t members < <(minipc_md_member_by_id "$uuid")
if [ "${#members[@]}" -lt 1 ]; then
  echo "No RAID members found for UUID $uuid (by-id scan)" >&2
  exit 1
fi

minipc_md_write_conf "$MD_DEV" "$uuid" "${members[@]}"
echo "Updated /etc/mdadm/mdadm.conf with ${#members[@]} member(s):"
printf '  %s\n' "${members[@]}"
