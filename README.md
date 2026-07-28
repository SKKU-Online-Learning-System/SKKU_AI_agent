# SKKU Course Agent

성균관대학교 강의자료 기반 코스 에이전트 MVP입니다. 현재 인증·과목 관리·자료 처리·과목별 검색과 교수자 디버그 UI까지 구현되어 있습니다. LLM 답변 생성은 후속 단계입니다.

## 구성

```text
apps/frontend     Next.js
apps/backend      FastAPI, SQLAlchemy, Alembic
packages/ai_rag   RAG 공통 모듈
docs              제품·기술 문서
```

Python 패키지는 루트 `uv` 워크스페이스로, 프론트엔드는 npm workspace로 관리합니다.

## 빠른 시작

필수 도구: [uv](https://docs.astral.sh/uv/), Python 3.9+, Node.js, Docker

저장소 루트에서 실행합니다.

```powershell
Copy-Item .env.example .env
Copy-Item apps\frontend\.env.local.example apps\frontend\.env.local

uv sync --locked --all-packages --all-extras
npm.cmd install
docker compose up -d db

uv run --all-packages --all-extras alembic -c apps/backend/alembic.ini upgrade head
uv run --all-packages --all-extras python -m app.db.seed
```

API와 웹은 별도 터미널에서 실행합니다.

```powershell
uv run --all-packages --all-extras uvicorn app.main:app --reload --app-dir apps/backend --host 0.0.0.0 --port 8000
```

```powershell
npm.cmd run dev:frontend
```

- 웹: `http://localhost:3000`
- API 문서: `http://localhost:8000/docs`
- 상태 확인: `http://localhost:8000/api/health`

## Seed 계정

공통 비밀번호: `password123`

| 역할 | 이메일 |
| --- | --- |
| 관리자 | `admin@skku.edu` |
| 교수자 | `professor@skku.edu` |
| 학생 | `student@skku.edu` |

## 문서 처리

지원 형식은 TXT, PDF, DOCX, PPTX입니다. 스캔 PDF는 OCR을 지원하지 않습니다.

```text
upload(pending) → process(processing) → text extraction
→ chunk → embedding → DocumentChunk 저장 → completed/failed
```

기본값은 외부 API가 필요 없는 deterministic mock embedding입니다. 실제 OpenAI embedding은 `.env`에서 `USE_MOCK_EMBEDDING=false`와 `OPENAI_API_KEY`를 설정합니다.

검색은 완료된 자료만 대상으로 하며 `course_id` 권한과 범위를 강제합니다. 현재 JSON embedding을 애플리케이션에서 cosine 비교합니다.

주요 자료 처리 API:

| 메서드 | 경로 |
| --- | --- |
| POST | `/api/courses/{course_id}/materials` |
| POST | `/api/courses/{course_id}/materials/{material_id}/process` |
| POST | `/api/courses/{course_id}/materials/{material_id}/reprocess` |
| GET | `/api/courses/{course_id}/materials/{material_id}/processing-status` |
| GET | `/api/courses/{course_id}/rag/status` |
| POST | `/api/rag/search` |

교수자는 `/professor/rag-debug` 또는 과목별 `/professor/courses/{courseId}/rag-debug`에서 점수와 출처 청크를 확인할 수 있습니다.

샘플 자료 업로드부터 검색까지 확인하려면 API 실행 후 다음 명령을 사용합니다.

```powershell
uv run --locked --all-packages --all-extras python scripts/rag_smoke_test.py
```

## 테스트

```powershell
uv run --locked --all-packages --all-extras pytest apps/backend/tests
uv run --locked --all-packages --all-extras pytest packages/ai_rag/tests
uv run --locked --all-packages --all-extras ruff check apps/backend packages/ai_rag

npm.cmd run test --workspace @skku-course-agent/frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run build:frontend
```

## uv 규칙

- 루트 `.venv`와 `uv.lock` 하나를 사용합니다.
- 설치는 `uv sync --locked --all-packages --all-extras`로 재현합니다.
- 의존성은 `uv add --package <workspace-package> <dependency>`로 변경합니다.
- `pyproject.toml` 변경 후 `uv lock`을 실행하고 `uv.lock`을 함께 커밋합니다.
- 직접 `pip install`하거나 패키지별 가상환경을 만들지 않습니다.

상세 설계와 로드맵은 [기술 명세](docs/TEC_SPEC.md)를 참고하세요.
