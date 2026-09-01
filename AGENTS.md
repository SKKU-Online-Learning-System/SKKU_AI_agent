# Repository Guidelines

## Product & Technical Context

Treat `docs/PRD.md` and `docs/TEC_SPEC.md` as the product source of truth. The MVP is an SKKU course agent: students ask questions, professors upload materials and inspect logs, and admins manage courses, users, permissions, and logs/statistics. RAG answers must use uploaded materials first, show sources, state when material is insufficient, save logs, and apply SAFE guardrails. Assignment or exam-answer requests should become hints, concepts, and learning guidance.

## Project Structure & Module Organization

This monorepo keeps the Next.js UI in `apps/frontend/app`, the FastAPI service in `apps/backend/app`, backend tests in `apps/backend/tests`, shared TypeScript types and schema in `packages/shared`, and Python RAG code/tests in `packages/ai_rag`. The COURSE AGENT lives in `apps/backend/app/services/voice` with routes in `apps/backend/app/api/routes/voice.py` and UI in `apps/frontend/app/components/course-agent`. Database setup lives in `infra/postgres/init`; planning and architecture docs live in `docs`.

## UI Reference

The web app clones the SKKU i-Campus layout (Canvas LMS, <https://canvas.skku.edu/>): a 76px dark-blue global rail, a 64px top bar, and a 204px course menu. Keep the i-Campus menu entries this MVP does not implement visible but inactive rather than removing them, so the shell keeps matching the real LMS. Shell styles live in `apps/frontend/app/globals.css`; COURSE AGENT styles in `apps/frontend/app/course-agent.css`.

## Architecture & Data Boundaries

The implementation follows the spec's frontend -> backend REST/WebSocket -> AI/RAG -> storage flow. Storage uses PostgreSQL/pgvector plus uploaded files. Enforce role and course access in the backend: students only active accessible courses, professors only assigned courses, admins all resources. Keep RAG retrieval filtered by `course_id`, preserve answer source metadata, and keep RAG internals replaceable behind service boundaries.

All text and voice LLM generation must go through `LLMService`/provider adapters. The default provider is the external school Model Server: typed answers and External Brain use the Text Qwen profile, while the realtime cascade uses the Voice Qwen profile. `brain.py` must not call a model SDK or inference HTTP endpoint directly. Anthropic is a legacy comparison adapter only.

Realtime speech orchestration must stay behind the `Transport` boundary. The default `local_cascade` path performs application-side CPU Silero VAD, calls the external Speech Server for ASR/TTS, and reuses the existing COURSE AGENT brain for RAG, tools, SAFE, memory, visualization and teaching modes. Grok remains a legacy transport selected only through the transport factory; API routes must not construct provider implementations directly. The frontend must remain provider-neutral.

The application repository must never load Qwen weights or add CUDA/vLLM/qwen-asr/qwen-tts runtimes. GPU inference belongs to `SKKU_AI_model_server`. CPU-only dependencies needed for orchestration, such as Silero VAD, are allowed and must not resolve CUDA PyTorch wheels. Trusted web search is application-owned through self-hosted SearXNG and professor-managed allowlists; every returned URL must be revalidated locally before use.

COURSE AGENT is bound by the same RBAC, SAFE, course-scoped RAG, citation and ChatLog rules as typed chat. WebSocket clients authenticate with the same JWT passed as a `token` query parameter. Students ask questions only through COURSE AGENT; do not reintroduce a separate "AI 질문" menu or course tab. 대화 이력 links back into COURSE AGENT with `?sessionId=`, and the backend rehydrates that conversation into the agent session before answering.

## Build, Test, and Development Commands

Run `bash run.sh` from the repo root for local Docker development: it starts PostgreSQL/pgvector, applies migrations and seed, then runs FastAPI on port 8000 and Next.js on port 3000. The external Model Server and SearXNG, when used, are separate processes and are not started by this repository. Run `bash test.sh` for Python tests, Ruff, and the frontend test/typecheck/lint sweep. Both scripts use the `.venv-app` environment, not the editor's `.venv`. Use `npm run build:frontend`, `npm run lint`, and `npm run typecheck` before frontend/shared changes. Unit tests must mock provider HTTP calls and must not require a live Model Server.

For the school Backend.AI compute session use `.env.backendai.example` plus `bash run_backendai.sh`; do not add Docker-in-Docker or try to start the Model Server from the application repository. Backend.AI startup requires a reachable PostgreSQL `DATABASE_URL`, verifies the already-running loopback Model Server, and directly binds FastAPI/Next.js to `0.0.0.0:8000`/`:3000`. Use `bash healthcheck_backendai.sh` and `bash stop_backendai.sh` for that runtime. Keep ports 8001/8002/8010 internal to the compute session.

## Coding Style & Naming Conventions

Python targets 3.12+, 4-space indentation, type hints where useful, and Ruff's 100-character line length. TypeScript uses 2-space indentation, double quotes, semicolons, and exported domain types from `packages/shared`. Prefer resource-based backend route modules and descriptive names such as `CourseMaterial`, `rag_service`, and `test_health.py`.

## Testing Guidelines

Use `pytest` with files named `test_*.py`. Cover behavior from the specs: login, JWT/role checks, course access, upload validation, RAG search, sourced answers, material-insufficient responses, SAFE handling, log persistence, provider selection, tool-result round trips, trusted-domain enforcement, local voice ASR/LLM/TTS failures and barge-in cancellation. For TypeScript, run the configured frontend tests, lint and typecheck. Do not delete or skip regression tests to make a provider migration pass.

## Commit & Pull Request Guidelines

Git history currently uses short messages, so keep commits concise and imperative, for example `Add course material upload`. PRs should summarize scope, list verification commands, link related docs/issues, and include screenshots for visible UI changes.

## Security & Configuration Tips

Copy `.env.example` to `.env`. Never commit API keys, JWT secrets, uploads, vector stores, caches, or local environment files. Validate upload extensions and sizes, store internal filenames as UUIDs, hash passwords, and return clear 401/403/404/422-style errors. Do not expose provider stack traces or full student transcripts in production logs by default.
