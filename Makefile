.PHONY: dev-db dev-api dev-web test-api test-rag typecheck-web

dev-db:
	docker compose up -d db

dev-api:
	uvicorn app.main:app --reload --app-dir apps/backend --host 0.0.0.0 --port 8000

dev-web:
	npm run dev:frontend

test-api:
	cd apps/backend && pytest

test-rag:
	cd packages/ai_rag && pytest

typecheck-web:
	npm run typecheck --workspaces --if-present
