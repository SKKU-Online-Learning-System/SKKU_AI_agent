# Repository Guidelines

## Product & Technical Context

Treat `docs/PRD.md` and `docs/TEC_SPEC.md` as the product source of truth. The MVP is an SKKU course agent: students ask questions, professors upload materials and inspect logs, and admins manage courses, users, permissions, and logs/statistics. RAG answers must use uploaded materials first, show sources, state when material is insufficient, save logs, and apply SAFE guardrails. Assignment or exam-answer requests should become hints, concepts, and learning guidance.

## Project Structure & Module Organization

This monorepo keeps the Next.js UI in `apps/frontend/app`, the FastAPI service in `apps/backend/app`, backend tests in `apps/backend/tests`, shared TypeScript types and schema in `packages/shared`, and Python RAG code/tests in `packages/ai_rag`. The COURSE AGENT (ported from `kingo-voice-agent`) lives in `apps/backend/app/services/voice` with routes in `apps/backend/app/api/routes/voice.py` and UI in `apps/frontend/app/components/course-agent`. Database setup lives in `infra/postgres/init`; planning and architecture docs live in `docs`.

## UI Reference

The web app clones the SKKU i-Campus layout (Canvas LMS, <https://canvas.skku.edu/>): a 76px dark-blue global rail, a 64px top bar, and a 204px course menu. Keep the i-Campus menu entries this MVP does not implement visible but inactive rather than removing them, so the shell keeps matching the real LMS. Shell styles live in `apps/frontend/app/globals.css`; COURSE AGENT styles in `apps/frontend/app/course-agent.css`.

## Architecture & Data Boundaries

The implementation follows the spec's frontend -> backend REST -> AI/RAG -> storage flow. Storage uses PostgreSQL/pgvector plus uploaded files. Enforce role and course access in the backend: students only active accessible courses, professors only assigned courses, admins all resources. Keep RAG retrieval filtered by `course_id`, preserve answer source metadata, and keep RAG internals replaceable behind service boundaries. COURSE AGENT is bound by the same rules: it generates answers through `LLMService` (Qwen, or the mock), its `search_course_materials` tool goes through `RagService`, its turns run through `SafetyGuardService`, and every turn is written to `ChatLog`. Keep provider calls inside `LLMService` — `brain.py` must not talk to a model SDK directly. The only exception is the existing realtime speech-to-speech leg (`grok_live.py`), which uses xAI. WebSocket clients authenticate with the same JWT passed as a `token` query parameter. Students ask questions only through COURSE AGENT; do not reintroduce a separate "AI 질문" menu or course tab. 대화 이력 links back into COURSE AGENT with `?sessionId=`, and the backend rehydrates that conversation into the agent session before answering.

## Build, Test, and Development Commands

Run `bash run.sh` from the repo root: it starts PostgreSQL/pgvector, applies migrations and seed, then runs FastAPI on port 8000 and Next.js on port 3000. Run `bash test.sh` for Python tests, Ruff, and the frontend test/typecheck/lint sweep. Both scripts use the `.venv-app` environment, not the editor's `.venv`. Use `npm run build:frontend`, `npm run lint`, and `npm run typecheck` before frontend/shared changes.

## Coding Style & Naming Conventions

Python targets 3.12+, 4-space indentation, type hints where useful, and Ruff's 100-character line length. TypeScript uses 2-space indentation, double quotes, semicolons, and exported domain types from `packages/shared`. Prefer resource-based backend route modules and descriptive names such as `CourseMaterial`, `rag_service`, and `test_health.py`.

## Testing Guidelines

Use `pytest` with files named `test_*.py`. Cover behavior from the specs: login, JWT/role checks, course access, upload validation, RAG search, sourced answers, material-insufficient responses, SAFE handling, and log persistence. For TypeScript, run lint and typecheck because no frontend test runner is currently configured.

## Commit & Pull Request Guidelines

Git history currently uses short messages, so keep commits concise and imperative, for example `Add course material upload`. PRs should summarize scope, list verification commands, link related docs/issues, and include screenshots for visible UI changes.

## Security & Configuration Tips

Copy `.env.example` to `.env`. Never commit API keys, JWT secrets, uploads, vector stores, caches, or local environment files. Validate upload extensions and sizes, store internal filenames as UUIDs, hash passwords, and return clear 401/403/404/422-style errors.
