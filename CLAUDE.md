# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`AGENTS.md` holds the repository conventions (structure, coding style, commit and PR rules) and is
still authoritative for those. This file covers the commands and the cross-file architecture.

## Commands

`run.sh` and `test.sh` are the entry points. Both force `UV_PROJECT_ENVIRONMENT=.venv-app` — the
editor's `.venv` is a different environment and its Ruff LSP locks `ruff.exe`, which breaks
`uv sync`. Never run backend tooling out of `.venv`.

```bash
bash run.sh        # .env + deps + docker db + alembic upgrade + seed + API:8000 + web:3000
bash test.sh       # pytest, ruff, vitest, typecheck, lint
```

Individual steps:

```bash
# Backend (always through .venv-app)
UV_PROJECT_ENVIRONMENT=.venv-app uv sync --all-packages --extra dev --extra voice
.venv-app/Scripts/python.exe -m pytest apps/backend/tests -q
.venv-app/Scripts/python.exe -m pytest apps/backend/tests/test_voice_api.py::test_reset_clears_the_conversation
.venv-app/Scripts/python.exe -m ruff check apps/backend packages

# Frontend
npm run build:frontend
npm run typecheck
npm run lint
npx vitest run --dir apps/frontend                     # or: cd apps/frontend && npx vitest run
cd apps/frontend && npx vitest run app/lib/auth.test.ts

# Database
docker compose up -d --wait db
UV_PROJECT_ENVIRONMENT=.venv-app uv run alembic -c apps/backend/alembic.ini upgrade head
UV_PROJECT_ENVIRONMENT=.venv-app uv run python -m app.db.seed
```

Two gotchas:

- **Deleting a route requires clearing `apps/frontend/.next`.** Next.js keeps generated route types
  there, and a stale one fails `next build` and `tsc --noEmit` with "Cannot find module
  `../../../app/.../page.js`".
- `pytest` currently has ~12 pre-existing failures (`test_materials_api`, `test_migrations`,
  `test_database_schema`, `test_chat_sessions_api`) plus 5 modules that fail at collection on a
  missing `SQLAlchemyLocalVectorStoreService`. Compare against that baseline before blaming a change.

Python is 3.12+. The `voice` extra installs the optional Moss memory SDK; the `vad` extra installs
`webrtcvad-wheels`, which needs a C toolchain and is deliberately left out of the default install.

## Architecture

Monorepo: `apps/frontend` (Next.js App Router), `apps/backend` (FastAPI), `packages/shared`
(TypeScript domain types), `packages/ai_rag` (standalone RAG package), `infra/postgres/init`
(pgvector bootstrap). Product source of truth is `docs/PRD.md` and `docs/TEC_SPEC.md`.

### Two answer paths, one boundary

There are two chat surfaces and they must not diverge:

1. `POST /api/chat` → `ChatService` — the plain RAG chatbot.
2. `POST /api/voice/courses/{id}/answer-text[/stream]` and `WS .../stream` → COURSE AGENT's
   `brain.think()`, the only question surface students actually see.

Both go through `SafetyGuardService` for guardrails, `RagService` for retrieval, `LLMService` for
generation, and both persist to `ChatSession`/`ChatLog`. **All model provider calls live in
`app/services/llm_service.py`** — `brain.py` must never import a model SDK. The one exception is
`app/services/voice/grok_live.py`, the existing xAI Grok realtime speech-to-speech transport.

`LLMService` has two modes throughout. With `USE_MOCK_LLM=true` (the default) a deterministic mock
answers, including a scripted tool-use turn, so the whole product runs with no API key. That is why
tests can exercise the agent end to end.

### Retrieval pipeline

Upload → `MaterialProcessingService.process_material` claims the row (status guard prevents
concurrent processing) → `DocumentParserService` → `ChunkingService` → `EmbeddingService` →
`VectorStoreService.replace_material_chunks`. Retrieval is always filtered by `course_id`;
`RagService.retrieve` returns a `RetrievalOutcome` whose `summary.reason` distinguishes
`NO_PROCESSED_MATERIAL` from `NO_RELEVANT_CONTEXT`, and `ChatService` turns that into the
`answer_source_type` the UI badges. Sources are built server-side from search results, never from
model output.

`VECTOR_SEARCH_MODE` switches between in-Python cosine similarity and pgvector. The default
embedding provider is a local hash, so `RAG_SCORE_THRESHOLD` is tuned low (0.1); raise it to ~0.3
with a real embedding model.

**There are two parser modules and only one is live.** The pipeline calls
`app/services/document_parser.py` (`parse_material`); `app/services/document_parser_service.py` is
an older duplicate that only the stale tests import. Same trap in `chunking_service`
(`create_chunks` is live, `ParagraphChunkingService` no longer exists) and
`vector_store_service` (`SQLAlchemyLocalVectorStoreService` no longer exists). Those stale imports
are exactly what the pre-existing collection failures are. Fix the live module, and check
`material_processing_service._run_pipeline` for what is actually wired.

### COURSE AGENT (`app/services/voice/`)

Ported from `github.com/lyh030725/kingo-voice-agent`, rewired to this project:

- `brain.py` — six-tool agent loop. `TOOLS` stays in OpenAI-compatible schema shape for both Qwen
  text generation and the Grok realtime path. Tool results travel as assistant `tool_calls` followed
  by `role=tool` messages. The two context operations (`recall_weak_concepts`,
  `search_course_materials`) are prefetched server-side before the model call.
- `search_course_materials` calls `RagService` (course-scoped pgvector), not a private PDF index, so
  citations keep the `filename p.page` shape professors see elsewhere. It opens its own
  `SessionLocal` because it runs inside tool dispatch, off the request session.
- `search_trusted_web` uses Qwen's DashScope native web search with the professor-managed allowlist,
  then **re-checks every returned host locally** before any URL reaches a student.
- `session_store.py` keeps one `VoiceContext` per `(user, course)` in process. Its lock is an
  `RLock` on purpose: `get_context()` calls `memory_store()` while holding it.
- `moss_memory.py` — weak-concept memory keyed by user id. Falls back to
  `uploads/voice/weak-concepts.json` when Moss credentials or quota are missing.
- `voice_log.py` — writes every turn (typed and spoken) into `ChatLog` so professor and admin log
  screens see voice traffic for free, and `restore_history()` rehydrates a conversation reopened
  from 대화 이력.
- `turn_detector.py` — the week-3 client-side VAD fallback, kept but not on the default path
  (Grok uses server VAD). Its `webrtcvad` import is lazy.

WebSockets cannot set headers, so `WS /api/voice/courses/{id}/stream` takes the JWT as a `token`
query parameter and re-runs `authorize_course_access` itself.

### Frontend

The UI is a clone of SKKU i-Campus (Canvas LMS, <https://canvas.skku.edu/>): a 76px dark-blue global
rail, a 64px top bar, a 204px course menu. **i-Campus menu entries this MVP does not implement stay
visible but inactive** (rendered as `<span>` instead of `<Link>`) so the shell keeps matching the
real LMS — do not delete them to "clean up".

`AppShell` renders the top bar for role pages; inside a course, `CourseWorkspaceClient` renders its
own identical top bar with the course context, which is why `AppShell` suppresses its own when
`data-course-workspace="true"`.

Students have exactly one question surface: COURSE AGENT inside a course. There is no separate
"AI 질문" menu item, course tab, or route — 대화 이력 links back into COURSE AGENT with
`?sessionId=`, which the backend rehydrates. Do not reintroduce them.

Styles: `app/globals.css` (shell and pages), `app/course-agent.css` (Course Agent symbol and chat panel).
`packages/shared` exports the domain types; `app/lib/api.ts` and `app/lib/voice-api.ts` are the only
places that talk to the backend.

## Configuration

Copy `.env.example` to `.env`. Notable behaviour:

- `USE_MOCK_LLM=true` and the local hash embedding mean the whole app runs with no API key.
- `QWEN_API_KEY` + `QWEN_MODEL` drive both `/api/chat` and COURSE AGENT's text answers.
- `XAI_API_KEY` is only for hands-free voice. Blank leaves the mic button disabled while text chat
  keeps working; do not gate text answers on it.
- `MOSS_PROJECT_ID`/`MOSS_PROJECT_KEY` are optional; without them weak concepts go to a local file.
- Settings are read through `app.core.config.Settings` (pydantic-settings). Do not add a second
  dotenv loader — a `load_dotenv()` anywhere leaks `.env` into `os.environ` and silently changes
  `JWT_SECRET` resolution for the whole app.
