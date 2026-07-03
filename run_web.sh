#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

HOST="${VRSTUDY_HOST:-0.0.0.0}"
PORT="${VRSTUDY_PORT:-8765}"

exec python -m uvicorn vrstudy_web.app:app --host "$HOST" --port "$PORT"
