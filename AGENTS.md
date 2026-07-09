# Repository Guidelines

## Product & Technical Context

Treat `docs/PRD.md` and `docs/TEC_SPEC.md` as the product source of truth. The MVP is an SKKU course agent: students ask questions, professors upload materials and inspect logs, and admins manage courses, users, permissions, and logs/statistics. RAG answers must use uploaded materials first, show sources, state when material is insufficient, save logs, and apply SAFE guardrails. Assignment or exam-answer requests should become hints, concepts, and learning guidance.

## Project Structure & Module Organization

This monorepo keeps the Next.js UI in `apps/frontend/app`, the FastAPI service in `apps/backend/app`, backend tests in `apps/backend/tests`, shared TypeScript types and schema in `packages/shared`, and Python RAG code/tests in `packages/ai_rag`. Database setup lives in `infra/postgres/init`; planning and architecture docs live in `docs`.

## Architecture & Data Boundaries

The implementation follows the spec's frontend -> backend REST -> AI/RAG -> storage flow. Storage uses PostgreSQL/pgvector plus uploaded files. Enforce role and course access in the backend: students only active accessible courses, professors only assigned courses, admins all resources. Keep RAG retrieval filtered by `course_id`, preserve answer source metadata, and keep RAG internals replaceable behind service boundaries.

## Build, Test, and Development Commands

Run `npm install` once at the root. Use `make dev-db` for PostgreSQL/pgvector, `make dev-api` for FastAPI on port 8000, and `make dev-web` or `npm run dev:frontend` for Next.js on port 3000. Use `npm run build:frontend`, `npm run lint`, and `npm run typecheck` before frontend/shared changes. Run `make test-api` and `make test-rag` for Python tests.

## Coding Style & Naming Conventions

Python targets 3.9+, 4-space indentation, type hints where useful, and Ruff's 100-character line length. TypeScript uses 2-space indentation, double quotes, semicolons, and exported domain types from `packages/shared`. Prefer resource-based backend route modules and descriptive names such as `CourseMaterial`, `rag_service`, and `test_health.py`.

## Testing Guidelines

Use `pytest` with files named `test_*.py`. Cover behavior from the specs: login, JWT/role checks, course access, upload validation, RAG search, sourced answers, material-insufficient responses, SAFE handling, and log persistence. For TypeScript, run lint and typecheck because no frontend test runner is currently configured.

## Commit & Pull Request Guidelines

Git history currently uses short messages, so keep commits concise and imperative, for example `Add course material upload`. PRs should summarize scope, list verification commands, link related docs/issues, and include screenshots for visible UI changes.

## Security & Configuration Tips

Copy `.env.example` to `.env`. Never commit API keys, JWT secrets, uploads, vector stores, caches, or local environment files. Validate upload extensions and sizes, store internal filenames as UUIDs, hash passwords, and return clear 401/403/404/422-style errors.
