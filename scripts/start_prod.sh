#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a
fi

export APP_ENV="${APP_ENV:-production}"
HOST="${APP_HOST:-0.0.0.0}"
PORT="${APP_PORT:-8000}"
WORKERS="${APP_WORKERS:-3}"
TIMEOUT="${APP_TIMEOUT:-120}"
GRACEFUL_TIMEOUT="${APP_GRACEFUL_TIMEOUT:-30}"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Error: .venv topilmadi. Avval virtualenv yarating."
  exit 1
fi

exec .venv/bin/gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  --bind "${HOST}:${PORT}" \
  --workers "${WORKERS}" \
  --timeout "${TIMEOUT}" \
  --graceful-timeout "${GRACEFUL_TIMEOUT}" \
  --access-logfile "-" \
  --error-logfile "-"
