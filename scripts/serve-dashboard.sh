#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${DASHBOARD_PORT:-8080}"
HOST="${DASHBOARD_HOST:-0.0.0.0}"

cd "$ROOT"
exec "$ROOT/.venv/bin/uvicorn" src.web.app:app --host "$HOST" --port "$PORT"
