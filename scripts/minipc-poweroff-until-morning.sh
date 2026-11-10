#!/bin/bash
set -euo pipefail
WAKE="09:00"
SLEEP="21:00"

to_seconds() {
  local hm="$1"
  date -d "1970-01-01 ${hm}:00 UTC" +%s
}

in_daytime_window() {
  local now wake sleep now_s wake_s sleep_s
  now=$(date +%H:%M)
  now_s=$(to_seconds "$now")
  wake_s=$(to_seconds "$WAKE")
  sleep_s=$(to_seconds "$SLEEP")
  if [ "$sleep_s" -gt "$wake_s" ]; then
    [ "$now_s" -ge "$wake_s" ] && [ "$now_s" -lt "$sleep_s" ]
  else
    [ "$now_s" -ge "$wake_s" ] || [ "$now_s" -lt "$sleep_s" ]
  fi
}

if in_daytime_window; then
  logger -t minipc-schedule "Daytime window ($WAKE–$SLEEP) — skip suspend, starting keep-awake"
  systemctl start minipc-keep-awake.service >/dev/null 2>&1 || true
  exit 0
fi

now=$(date +%s)
target=$(date -d "today $WAKE" +%s)
if [ "$target" -le $((now + 120)) ]; then
  target=$(date -d "tomorrow $WAKE" +%s)
fi
logger -t minipc-schedule "Stopping daytime keep-awake; suspending until $(date -d "@$target")"
systemctl stop minipc-keep-awake.service >/dev/null 2>&1 || true
exec /usr/sbin/rtcwake -m mem -t "$target"
