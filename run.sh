#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
UV="$(command -v uv || command -v uv.exe)"
# .venv is the editor's (its Ruff LSP locks ruff.exe and blocks uv sync)
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-.venv-app}"
export WSLENV="${WSLENV:+$WSLENV:}UV_PROJECT_ENVIRONMENT"
unset VIRTUAL_ENV  # silence uv's warning when the editor's .venv is activated

[ -f .env ] || cp .env.example .env
[ -f apps/frontend/.env.local ] || cp apps/frontend/.env.local.example apps/frontend/.env.local
[ -d node_modules ] || npm install

# Backend.AI prepends its system PyTorch libraries; prefer this app environment's
# matching CPU wheel so torch Python and native extensions cannot be mixed.
APP_TORCH_LIB="$(
  "$UV" run --locked --all-packages --extra dev --extra voice python -c '
import os, sysconfig
print(os.path.join(sysconfig.get_paths()["purelib"], "torch", "lib"))
'
)"
export LD_LIBRARY_PATH="${APP_TORCH_LIB}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"

echo "Verifying app voice runtime"
"$UV" run --locked --all-packages --extra dev --extra voice python -c '
import torch
from silero_vad import load_silero_vad
load_silero_vad(onnx=True)
print(f"voice torch={torch.__version__} vad=ready")
'

if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  docker compose up -d --wait db
else
  # ponytail: SQLite is for one Backend.AI dev session; use PostgreSQL for multi-replica deployment.
  export DATABASE_URL="sqlite:///${PWD}/course-agent.sqlite"
  export VECTOR_DB_PROVIDER="local"
  export VECTOR_DB_URL="${DATABASE_URL}"
  export VECTOR_SEARCH_MODE="local"
  export NEXT_PUBLIC_API_BASE_URL=""
  echo "Docker unavailable; using embedded SQLite at ${PWD}/course-agent.sqlite"
fi
"$UV" run --locked --all-packages --extra dev --extra voice alembic -c apps/backend/alembic.ini upgrade head
"$UV" run --locked --all-packages --extra dev --extra voice python -m app.db.seed

# ponytail: kill 0 tears down the whole process group; fine for one dev shell
trap 'kill 0' EXIT
"$UV" run --locked --all-packages --extra dev --extra voice uvicorn app.main:app --reload --app-dir apps/backend --port 8000 &
npm run dev:frontend
