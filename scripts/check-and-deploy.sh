#!/usr/bin/env bash
# Poll origin/main; pull and restart dashboard when new commits exist.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

git fetch origin main 2>/dev/null || git fetch origin

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse origin/main)"

if [[ "$LOCAL" == "$REMOTE" ]]; then
  echo "$(date -Is) up to date at $(git rev-parse --short HEAD)"
  exit 0
fi

echo "$(date -Is) deploy trigger: $(git rev-parse --short HEAD) -> $(git rev-parse --short origin/main)"
exec bash "$ROOT/scripts/pull-on-mini-pc.sh"
