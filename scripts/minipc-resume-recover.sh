#!/bin/bash
# After suspend/resume: restore LAN, Tailscale, daytime inhibit, and log health.
set -euo pipefail

LOG_TAG=minipc-resume
IFACE="${MINIPC_LAN_IFACE:-enp2s0f0}"

logger -t "$LOG_TAG" "Starting post-resume recovery"

sleep 2
udevadm settle 2>/dev/null || true

systemctl start minipc-keep-awake.service 2>/dev/null || true

if systemctl is-active --quiet NetworkManager.service; then
  systemctl restart NetworkManager.service 2>/dev/null || true
  sleep 3
  nmcli device connect "$IFACE" 2>/dev/null || nmcli networking on 2>/dev/null || true
else
  systemctl start NetworkManager.service 2>/dev/null || true
fi

if systemctl is-enabled --quiet tailscaled.service 2>/dev/null \
  && systemctl is-active --quiet tailscaled.service 2>/dev/null; then
  systemctl restart tailscaled.service 2>/dev/null || true
fi

if ip -br a show "$IFACE" 2>/dev/null | grep -qE '192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.'; then
  logger -t "$LOG_TAG" "LAN on $IFACE looks up"
else
  logger -t "$LOG_TAG" "WARN: no IPv4 on $IFACE after resume — NetworkManager restarted"
fi

systemctl start mini-pc-monitor.service 2>/dev/null || true

logger -t "$LOG_TAG" "Post-resume recovery finished"