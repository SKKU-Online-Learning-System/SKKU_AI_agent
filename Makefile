.PHONY: sync dev-db migrate-db seed-db dev-api dev-web test-api test-rag lint-python typecheck-web

sync:
	uv sync --locked --all-packages --all-extras

dev-db:
	docker compose up -d db

migrate-db:
	uv run --all-packages --all-extras alembic -c apps/backend/alembic.ini upgrade head

seed-db:
	uv run --all-packages --all-extras python -m app.db.seed

dev-api:
	uv run --all-packages --all-extras uvicorn app.main:app --reload --app-dir apps/backend --host 0.0.0.0 --port 8000

dev-web:
	npm run dev:frontend

test-api:
	uv run --all-packages --all-extras pytest apps/backend/tests

test-rag:
	uv run --all-packages --all-extras pytest packages/ai_rag/tests

lint-python:
	uv run --all-packages --all-extras ruff check apps/backend packages/ai_rag scripts

typecheck-web:
	npm run typecheck --workspaces --if-present
