#!/bin/bash
# Secondary recovery a few minutes after morning wake (if resume hook was too early or partial).
set -euo pipefail

IFACE="${MINIPC_LAN_IFACE:-enp2s0f0}"
LOG_TAG=minipc-wake-health

have_lan() {
  ip -br a show "$IFACE" 2>/dev/null | grep -qE '192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.'
}

if have_lan && curl -sf --max-time 3 http://127.0.0.1:8080/ >/dev/null 2>&1; then
  logger -t "$LOG_TAG" "OK: LAN and dashboard after wake"
  exit 0
fi

logger -t "$LOG_TAG" "Recovery pass: LAN or dashboard not ready"
/usr/local/sbin/minipc-resume-recover.sh 2>/dev/null || true
MINIPC_MEMBER_WAIT_MAX=30 /usr/local/sbin/minipc-ensure-storage.sh 2>/dev/null || true

sleep 5
if have_lan && curl -sf --max-time 5 http://127.0.0.1:8080/ >/dev/null 2>&1; then
  logger -t "$LOG_TAG" "OK after recovery pass"
  exit 0
fi

logger -t "$LOG_TAG" "WARN: still unhealthy after wake — manual reboot may be needed"
exit 0