#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${VIDEO_DOWNLOAD_HOST:-0.0.0.0}"
PORT="${VIDEO_DOWNLOAD_PORT:-8083}"

cd "$ROOT"
exec "$ROOT/.venv/bin/uvicorn" src.web.video_download_app:app --host "$HOST" --port "$PORT"
