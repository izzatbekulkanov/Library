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
PORT="${APP_PORT:-8001}"
WORKERS="${APP_WORKERS:-3}"
TIMEOUT="${APP_TIMEOUT:-120}"
GRACEFUL_TIMEOUT="${APP_GRACEFUL_TIMEOUT:-30}"
KEEP_ALIVE="${APP_KEEP_ALIVE:-30}"
MAX_REQUESTS="${APP_MAX_REQUESTS:-2000}"
MAX_REQUESTS_JITTER="${APP_MAX_REQUESTS_JITTER:-200}"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Error: .venv topilmadi. Avval virtualenv yarating."
  exit 1
fi

WORKER_CLASS="uvicorn_worker.UvicornWorker"
if ! .venv/bin/python -c "import uvicorn_worker" >/dev/null 2>&1; then
  WORKER_CLASS="uvicorn.workers.UvicornWorker"
fi

exec .venv/bin/gunicorn app.main:app \
  -k "${WORKER_CLASS}" \
  --bind "${HOST}:${PORT}" \
  --workers "${WORKERS}" \
  --timeout "${TIMEOUT}" \
  --graceful-timeout "${GRACEFUL_TIMEOUT}" \
  --keep-alive "${KEEP_ALIVE}" \
  --max-requests "${MAX_REQUESTS}" \
  --max-requests-jitter "${MAX_REQUESTS_JITTER}" \
  --worker-tmp-dir /dev/shm \
  --capture-output \
  --log-level info \
  --access-logfile "-" \
  --error-logfile "-"
