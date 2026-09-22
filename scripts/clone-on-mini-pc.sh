#!/usr/bin/env bash
# One-time clone on the mini-PC.

set -euo pipefail

TARGET="${1:-$HOME/mini-pc-monitor}"
REPO="${MINI_PC_MONITOR_REPO:-https://github.com/Merxius2/mini-pc-monitor.git}"

if [[ -d "$TARGET/.git" ]]; then
  echo "Already cloned at $TARGET"
  exit 0
fi

git clone "$REPO" "$TARGET"
cd "$TARGET"
bash scripts/install-dashboard-service.sh
bash scripts/install-deploy-trigger.sh
