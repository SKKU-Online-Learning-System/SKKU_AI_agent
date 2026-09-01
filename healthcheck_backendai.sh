#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
ROOT_DIR="$(pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

BACKEND_PORT="${BACKENDAI_BACKEND_PORT:-8000}"
FRONTEND_PORT="${BACKENDAI_FRONTEND_PORT:-3000}"
VENV_PATH="${UV_PROJECT_ENVIRONMENT:-.venv-app}"
if [[ "${VENV_PATH}" != /* ]]; then
  VENV_PATH="${ROOT_DIR}/${VENV_PATH}"
fi
PYTHON_BIN="${VENV_PATH}/bin/python"

failures=0

check_http() {
  local name="$1"
  local url="$2"
  echo "==> ${name}: ${url}"
  if body="$(curl -fsS --max-time 5 "${url}" 2>&1)"; then
    echo "${body}"
    echo "[HEALTHY] ${name}"
  else
    echo "${body}" >&2
    echo "[UNHEALTHY] ${name}" >&2
    failures=$((failures + 1))
  fi
}

check_http "Frontend" "http://127.0.0.1:${FRONTEND_PORT}/"
check_http "Backend" "http://127.0.0.1:${BACKEND_PORT}/api/health"
check_http "Application -> Model Server" "http://127.0.0.1:${BACKEND_PORT}/api/health/model-server"

if [[ -x "${PYTHON_BIN}" && -f "${ENV_FILE}" ]]; then
  echo "==> PostgreSQL"
  if "${PYTHON_BIN}" - <<'PY'
from sqlalchemy import create_engine, text
from app.core.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
try:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
finally:
    engine.dispose()
print("PostgreSQL connection: OK")
PY
  then
    echo "[HEALTHY] PostgreSQL"
  else
    echo "[UNHEALTHY] PostgreSQL" >&2
    failures=$((failures + 1))
  fi
else
  echo "[SKIPPED] PostgreSQL: Python environment or .env is missing"
fi

if (( failures > 0 )); then
  echo "${failures} Backend.AI component(s) are unhealthy." >&2
  exit 1
fi

echo "All Backend.AI application components are healthy."
