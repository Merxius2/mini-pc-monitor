#!/usr/bin/env bash
# Video download runs on the main dashboard (mini-pc-monitor, port 8080).
# This script disables the old standalone :8083 service if it was installed.
set -euo pipefail

SERVICE_NAME="video-download.service"

if systemctl list-unit-files "$SERVICE_NAME" &>/dev/null; then
  sudo systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
  echo "Disabled standalone $SERVICE_NAME (no longer used)."
fi

echo "Open Video download from the dashboard sidebar, or:"
echo "  http://192.168.1.30:8080/video-download"
