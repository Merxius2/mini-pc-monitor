#!/bin/bash
set -euo pipefail
WAKE="09:00"
now=$(date +%s)
target=$(date -d "today $WAKE" +%s)
if [ "$target" -le $((now + 120)) ]; then
  target=$(date -d "tomorrow $WAKE" +%s)
fi
logger -t minipc-schedule "Stopping daytime keep-awake; suspending until $(date -d "@$target")"
systemctl stop minipc-keep-awake.service >/dev/null 2>&1 || true
exec /usr/sbin/rtcwake -m mem -t "$target"
