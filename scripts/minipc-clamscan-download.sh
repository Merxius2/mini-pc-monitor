#!/bin/bash
# Transmission script-torrent-done: scan completed download with ClamAV.
set -euo pipefail

LIB="/usr/local/sbin/minipc-clamscan-lib.sh"
# shellcheck source=/dev/null
[ -f "$LIB" ] && . "$LIB"

LOG="${MINIPC_CLAM_LOG:-/mnt/storage/logs/clamav-scan.log}"
QUARANTINE="${MINIPC_CLAM_QUARANTINE:-/mnt/storage/quarantine}"
TARGET="${TR_TORRENT_DIR}/${TR_TORRENT_NAME}"

mkdir -p "$(dirname "$LOG")" "$QUARANTINE"

{
  echo "=== $(date -Iseconds) torrent done: $TARGET ==="
  if [ ! -e "$TARGET" ]; then
    echo "Missing path, skip"
    exit 0
  fi
  if ! systemctl is-active --quiet clamav-daemon.service; then
    echo "clamav-daemon not active, skip scan"
    exit 0
  fi
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' EXIT
  if minipc_clamdscan_run "$TARGET" "$QUARANTINE" "$tmp"; then
    scan_rc=0
  else
    scan_rc=$?
  fi
  if declare -F minipc_clamdscan_finish >/dev/null; then
    minipc_clamdscan_finish "$tmp" "$scan_rc" || true
  elif [ "$scan_rc" -eq 0 ]; then
    echo "OK: clean"
  else
    echo "INFECTED or scan error (see above)"
  fi
} >>"$LOG" 2>&1
