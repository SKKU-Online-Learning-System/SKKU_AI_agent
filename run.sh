#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

case "${1:-}" in
  "") DB_MODE=compose ;;
  --external-db) DB_MODE=external ;;
  -h|--help)
    printf '%s\n' "Usage: bash run.sh [--external-db]" \
      "Default: start the local Docker PostgreSQL, migrate, and seed only an empty database." \
      "--external-db: use DATABASE_URL and verify migrations without writing demo data."
    exit 0
    ;;
  *) echo "Usage: bash run.sh [--external-db]" >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
  echo "Usage: bash run.sh [--external-db]" >&2
  exit 2
fi
if [ "$DB_MODE" = compose ] && ! docker info >/dev/null 2>&1; then
  echo "Start Docker for the local PostgreSQL, or configure DATABASE_URL and use --external-db." >&2
  exit 1
fi

BACKEND_PORT="${BACKEND_PORT:-8000}"
if ! [[ "$BACKEND_PORT" =~ ^[1-9][0-9]{0,4}$ ]] || [ "$BACKEND_PORT" -gt 65535 ]; then
  echo "BACKEND_PORT must be between 1 and 65535." >&2
  exit 2
fi
if [ "$BACKEND_PORT" != 8000 ]; then
  export NEXT_PUBLIC_API_BASE_URL="${NEXT_PUBLIC_API_BASE_URL:-http://localhost:$BACKEND_PORT}"
fi

UV="$(command -v uv || command -v uv.exe)"
# .venv is the editor's (its Ruff LSP locks ruff.exe and blocks uv sync)
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-.venv-app}"
export WSLENV="${WSLENV:+$WSLENV:}UV_PROJECT_ENVIRONMENT"
unset VIRTUAL_ENV  # silence uv's warning when the editor's .venv is activated

[ -f .env ] || cp .env.example .env
[ -f apps/frontend/.env.local ] || cp apps/frontend/.env.local.example apps/frontend/.env.local
[ -d node_modules ] || npm install

app_run() {
  "$UV" run --locked --all-packages --extra dev --extra voice "$@"
}

app_run python - "$DB_MODE" <<'PY'
import sys
from sqlalchemy.engine import make_url
from app.core.config import get_settings

settings = get_settings()
url = make_url(settings.database_url)
if settings.app_env != "local":
    sys.exit("run.sh is for local development; set APP_ENV=local for your development instance.")
if url.drivername != "postgresql+psycopg":
    sys.exit("DATABASE_URL must use postgresql+psycopg:// (SQLite is not an app startup fallback).")
if sys.argv[1] == "compose" and (
    url.host not in {"localhost", "127.0.0.1"}
    or url.port not in {None, 5432}
    or url.database != "course_agent"
    or url.username != "course_agent"
    or url.query
):
    sys.exit("For a custom PostgreSQL connection, configure DATABASE_URL and use --external-db.")
PY

# Backend.AI prepends its system PyTorch libraries; prefer this app environment's
# matching CPU wheel so torch Python and native extensions cannot be mixed.
APP_TORCH_LIB="$(
  app_run python -c '
import os, sysconfig
print(os.path.join(sysconfig.get_paths()["purelib"], "torch", "lib"))
'
)"
# The interpreter of this app environment, for the reload loop below. A bare `python`
# there finds uv's base interpreter (CreateProcess looks in the parent's directory first),
# which has no uvicorn. Relative, because a non-ASCII user name in the absolute path did
# not survive the argv hand-off; backslashes, because CreateProcess does not resolve a
# relative program path written with forward slashes.
APP_PYTHON="$UV_PROJECT_ENVIRONMENT/bin/python"
[ -x "$UV_PROJECT_ENVIRONMENT/Scripts/python.exe" ] && APP_PYTHON="${UV_PROJECT_ENVIRONMENT//\//\\}\\Scripts\\python.exe"
export LD_LIBRARY_PATH="${APP_TORCH_LIB}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

echo "Verifying app voice runtime"
app_run python -c '
import torch
from silero_vad import load_silero_vad
load_silero_vad(onnx=True)
print(f"voice torch={torch.__version__} vad=ready")
'

if [ "$DB_MODE" = compose ]; then
  docker compose up -d --wait db
  app_run alembic -c apps/backend/alembic.ini upgrade head
  app_run python -m app.db.seed --if-empty
else
  if ! app_run alembic -c apps/backend/alembic.ini current --check-heads; then
    echo "Check DATABASE_URL and apply the migrations to the intended development database first." >&2
    exit 1
  fi
fi

# ponytail: kill 0 tears down the whole process group; fine for one dev shell
trap 'kill 0' EXIT
# Reload through watchfiles, not `uvicorn --reload`: on Windows uvicorn restarts its worker
# with CTRL_C_EVENT, which the console delivers to every process attached to it -- this shell
# and the Next dev server included -- so the first source edit took the whole app down.
# watchfiles terminates just the worker (the interpreter itself, no wrapper to orphan it).
# Watch only the backend source: a package write into .venv-app (or a Windows rescan of it)
# would otherwise restart the API mid-startup.
"$UV" run --locked --all-packages --extra dev --extra voice watchfiles --filter python   "$APP_PYTHON -m uvicorn app.main:app --app-dir apps/backend --port $BACKEND_PORT" apps/backend &
npm run dev:frontend
