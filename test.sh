#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
UV="$(command -v uv || command -v uv.exe)"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-.venv-app}"
export WSLENV="${WSLENV:+$WSLENV:}UV_PROJECT_ENVIRONMENT"
unset VIRTUAL_ENV  # silence uv's warning when the editor's .venv is activated

"$UV" run --locked --all-packages --extra dev --extra voice pytest
"$UV" run --locked --all-packages --extra dev --extra voice ruff check apps/backend packages/ai_rag scripts
npm run test --workspace @skku-course-agent/frontend
npm run typecheck
npm run lint
