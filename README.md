# SKKU Course Agent MVP

## 프로젝트 소개

성균관대학교 AI중심대학사업의 강의자료 기반 RAG 챗봇 MVP입니다. 학생은 과목을 선택해 질문하고, 교수자는 강의자료를 업로드하며, 관리자는 과목·사용자·자료를 관리하는 구조입니다.

이 문서는 현재 완료된 **2단계**를 처음부터 실행하고 검증하는 안내서입니다. 2단계는 인증, 역할 기반 접근 제어(RBAC), 과목 관리, 자료 파일 저장과 메타데이터 관리까지를 포함합니다. 자료 내용을 읽어 답하는 RAG 기능은 아직 연결하지 않았습니다.

## 2단계 구현 기능

- Argon2 비밀번호 검증, JWT 로그인, 현재 사용자 조회
- 관리자·교수자·학생 역할별 웹 경로 보호와 백엔드 권한 검사
- 관리자의 과목 생성, 조회, 수정, 활성화/비활성화
- 역할별 접근 가능한 과목 조회: 교수자는 담당 과목, 학생은 수강 중인 활성 과목
- 교수자(담당 과목)와 관리자의 자료 업로드·목록·삭제
- 업로드 파일과 `CourseMaterial` 메타데이터의 PostgreSQL 저장
- 자료 API의 처리 대기 상태(`processingStatus: "pending"`) 반환

## 기술 스택

- Frontend: Next.js + TypeScript
- Backend: FastAPI + SQLAlchemy + Alembic
- Database: PostgreSQL + pgvector
- AI/RAG: 독립 Python 패키지(`packages/ai_rag`), OpenAI API 연결을 위한 설정 보유
- 인증: Argon2, JWT (`python-jose`)
- 테스트: pytest, Vitest, ESLint, TypeScript

## 프로젝트 구조

```text
.
├── apps
│   ├── backend          # FastAPI API 서버와 Alembic 마이그레이션
│   └── frontend         # Next.js 웹 앱
├── packages
│   ├── ai_rag           # 임베딩, 검색, 생성 RAG 모듈의 향후 구현 경계
│   └── shared           # 공통 TypeScript 타입 및 JSON Schema
├── infra
│   └── postgres         # pgvector 초기화 스크립트
├── docs                 # PRD, 기술 명세, 아키텍처 문서
├── docker-compose.yml   # 로컬 PostgreSQL/pgvector
├── Makefile             # Linux/macOS용 개발·검증 단축 명령
├── .env.example         # API/DB용 로컬 환경변수 예시
└── apps/frontend/.env.local.example # Next.js 공개 환경변수 예시
```

## 사전 요구사항

- Docker Desktop 또는 Docker Engine과 Docker Compose
- Python 3.9 이상
- Node.js 및 npm (저장소는 npm 10.8.0을 기준으로 관리)
- `make`는 선택 사항입니다. Linux/macOS에서는 `Makefile` 단축 명령을 사용할 수 있고, Windows PowerShell에서는 아래의 직접 명령을 사용합니다.

먼저 저장소 루트에서 Python 패키지와 프런트엔드 의존성을 설치합니다.

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e "./packages/ai_rag[dev]"
python -m pip install -e "./apps/backend[dev]"
npm install
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".\packages\ai_rag[dev]"
& .\.venv\Scripts\python.exe -m pip install -e ".\apps\backend[dev]"
npm.cmd install
```

`npm` 명령이 PowerShell 실행 정책에 의해 `npm.ps1` 오류를 내면 `npm.cmd`를 계속 사용합니다. `npm.cmd install`의 audit 경고는 설치 실패가 아니며, 의존성 버전을 바꾸는 `npm audit fix --force`는 실행하지 마세요.

## 환경변수 설정

Linux/macOS:

```bash
cp .env.example .env
cp apps/frontend/.env.local.example apps/frontend/.env.local
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
Copy-Item apps\frontend\.env.local.example apps\frontend\.env.local
```

루트 `.env`는 API/DB 설정 파일입니다. 기본값은 `APP_ENV=local`, 로컬 Docker DB, 프런트엔드 Origin(`http://localhost:3000`)을 대상으로 합니다. 예시 `JWT_SECRET`은 로컬 개발 전용입니다. `APP_ENV`가 `local`이 아닌 환경에서는 예시 키를 사용할 수 없으며, 고유하게 생성한 32자 이상의 임의 키로 교체해야 API가 시작됩니다. 실제 배포 전에는 `OPENAI_API_KEY`도 설정하고, `.env`는 커밋하지 마세요.

| 변수 | 기본값 | 용도 |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://course_agent:course_agent@localhost:5432/course_agent` | API DB 연결 |
| `JWT_SECRET` | `replace-with-a-long-random-secret` | 로컬 전용 JWT 예시 키. 비로컬 환경은 고유한 32자 이상 키 필요 |
| `BACKEND_CORS_ORIGINS` | `http://localhost:3000` | 허용할 웹 Origin |
| `UPLOAD_DIR` | `uploads` | 업로드 파일 저장 루트 |
| `MAX_UPLOAD_SIZE_BYTES` | `20971520` | 파일당 최대 크기(20 MiB, 안내상 20MB) |
| `MAX_UPLOAD_REQUEST_SIZE_BYTES` | `22020096` | multipart 오버헤드를 포함한 업로드 요청 본문 한도(21 MiB) |
| `VECTOR_DB_PROVIDER` | `pgvector` | 향후 벡터 저장소 제공자 |
| `VECTOR_DB_COLLECTION` | `course_document_chunks` | 향후 문서 청크 컬렉션/테이블 이름 |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI 임베딩 모델 |
| `USE_MOCK_EMBEDDING` | `true` | 외부 API 없는 결정적 개발용 임베딩 사용 |
| `VECTOR_SEARCH_MODE` | `local` | 현재 JSON 임베딩의 애플리케이션 레벨 cosine 검색 |
| `RAG_TOP_K` | `5` | 기본 검색 결과 수(최대 20) |
| `RAG_SCORE_THRESHOLD` | `0.3` | 검색 결과 최소 cosine 유사도 |

프런트엔드 API 주소는 `apps/frontend/.env.local`에서 설정합니다. 이 파일의 예시는 `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000`이며, `apps/frontend/app/lib/api.ts`도 값이 없을 때 `http://localhost:8000`을 기본값으로 사용합니다. `.env.local`도 커밋하지 마세요.

환경변수를 바꾼 뒤에는 API와 Next.js 개발 서버를 다시 시작합니다.

## PostgreSQL 실행

`docker-compose.yml`은 `pgvector/pgvector:pg16` 이미지와 `course_agent` 사용자·DB를 포트 `5432`에서 실행합니다.

Linux/macOS:

```bash
docker compose up -d db
docker compose ps
# 선택 단축 명령: make dev-db
```

Windows PowerShell:

```powershell
docker compose up -d db
docker compose ps
```

DB 컨테이너가 `running` 또는 healthcheck가 `healthy`가 된 뒤 다음 단계로 진행합니다.

## 데이터베이스 마이그레이션

Alembic 마이그레이션은 `apps/backend`에서 실행해야 합니다. 위의 Python 가상환경을 먼저 설치한 상태여야 합니다.

Linux/macOS:

```bash
source .venv/bin/activate
make migrate-db
```

Windows PowerShell:

```powershell
Push-Location apps\backend
& ..\..\.venv\Scripts\python.exe -m alembic upgrade head
Pop-Location
```

## Seed 데이터 생성

Seed는 여러 번 실행해도 세 사용자, 두 과목, 학생의 접근 관계를 중복 생성하지 않고 동일한 데모 값으로 맞춥니다.

Linux/macOS:

```bash
source .venv/bin/activate
make seed-db
```

Windows PowerShell:

```powershell
Push-Location apps\backend
& ..\..\.venv\Scripts\python.exe -m app.db.seed
Pop-Location
```

성공하면 `users=3 courses=2 course_access=2`가 출력됩니다. 마이그레이션 또는 Seed가 `password authentication failed`로 실패하면 Alembic 문제가 아니라 기존 Docker 볼륨의 PostgreSQL 자격 증명이 `.env`/`docker-compose.yml`과 다른지 먼저 확인하세요. 로컬 개발 데이터를 버려도 되는 경우에만 `docker compose down -v` 후 DB를 다시 만들 수 있습니다.

## 로컬 서버 실행

터미널을 두 개 열어 API와 웹을 각각 실행합니다. 아래 명령은 저장소 루트에서 실행합니다.

API 서버 (포트 8000)

Linux/macOS:

```bash
source .venv/bin/activate
make dev-api
```

Windows PowerShell:

```powershell
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir apps/backend --host 0.0.0.0 --port 8000
```

웹 서버 (포트 3000)

Linux/macOS:

```bash
npm run dev:frontend
```

Windows PowerShell:

```powershell
npm.cmd run dev:frontend
```

브라우저에서 `http://localhost:3000`을 열고, API 상태는 다음으로 확인합니다.

Linux/macOS:

```bash
curl http://localhost:8000/api/health
```

Windows PowerShell:

```powershell
Invoke-RestMethod http://localhost:8000/api/health
```

FastAPI 대화형 API 문서는 `http://localhost:8000/docs`에 있습니다.

## 테스트 계정

모든 Seed 계정의 비밀번호는 `password123`입니다.

| 역할 | 이메일 | 기본 접속 결과 |
| --- | --- | --- |
| 관리자 | `admin@skku.edu` | 전체 과목 관리 화면 |
| 교수자 | `professor@skku.edu` | 두 예시 과목과 자료 관리 화면 |
| 학생 | `student@skku.edu` | 접근 가능한 활성 과목 목록 |

Seed 과목과 관계는 다음과 같습니다.

| 학기 | 과목 | 담당 교수자 | 학생 접근 |
| --- | --- | --- | --- |
| `2026-2` | 인공지능개론 | `professor@skku.edu` | `student@skku.edu` 허용 |
| `2026-2` | 소프트웨어공학 | `professor@skku.edu` | `student@skku.edu` 허용 |

## 역할별 접속 경로

로그인 페이지는 `/login`이며, 성공 시 역할별 기본 경로로 이동합니다. 다른 역할의 경로를 직접 열면 프런트엔드는 `/forbidden`으로 이동하고, API도 별도로 401/403을 검사합니다.

| 역할 | 경로 |
| --- | --- |
| 관리자 | `/admin`, `/admin/courses`, `/admin/courses/new` |
| 교수자 | `/professor`, `/professor/courses`, `/professor/materials` |
| 학생 | `/student`, `/student/courses` |

## 주요 API

모든 `/api` 경로 중 인증 필요 항목에는 `Authorization: Bearer <access_token>` 헤더가 필요합니다. JSON 모델의 필드명은 camelCase로 반환됩니다.

| 메서드 | 경로 | 권한/상태 | 설명 |
| --- | --- | --- | --- |
| GET | `/api/health` | 공개, 200 | API 환경 및 벡터 설정 상태 |
| POST | `/api/auth/login` | 공개, 200 | 이메일·비밀번호 로그인, JWT와 사용자 반환 |
| GET | `/api/auth/me` | 인증 필요, 200 | 현재 사용자 조회 |
| GET | `/api/courses` | 인증 필요, 200 | 역할별 접근 가능한 과목 목록 |
| POST | `/api/courses` | 관리자, 201 | 호환용 과목 생성 API |
| GET | `/api/courses/{course_id}` | 과목 접근 권한, 200 | 단일 과목 조회 |
| GET | `/api/courses/{course_id}/materials` | 과목 접근 권한, 200 | 자료 목록(최신순) |
| POST | `/api/courses/{course_id}/materials` | 과목 관리 권한, **202** | `multipart/form-data`의 `file` 업로드 |
| DELETE | `/api/courses/{course_id}/materials/{material_id}` | 과목 관리 권한, 204 | DB 메타데이터와 저장 파일 삭제 |
| GET | `/api/admin/stats` | 관리자, 200 | 현재 사용자·과목·자료 수 |
| GET | `/api/admin/users` | 관리자, 200 | 사용자 목록 (`role` 필터 선택) |
| GET/POST | `/api/admin/courses` | 관리자, 200/201 | 관리자용 과목 목록/생성 |
| GET/PATCH | `/api/admin/courses/{course_id}` | 관리자, 200 | 과목 상세/수정 |
| PATCH | `/api/admin/courses/{course_id}/deactivate` | 관리자, 200 | 과목 비활성화 |
| PATCH | `/api/admin/courses/{course_id}/activate` | 관리자, 200 | 과목 활성화 |
| GET | `/api/admin/courses/{course_id}/access` | 관리자, 200 | 과목 접근 사용자 목록 |
| POST | `/api/chat/sessions` | 인증·과목 접근, 201 | 3단계용 세션 응답 계약(영속 저장 미구현) |
| POST | `/api/chat/sessions/{session_id}/messages` | 인증·과목 접근, 200 | 3단계용 답변 경계(실제 RAG 미연결) |

로그인과 JWT 확인 예시는 다음과 같습니다.

Linux/macOS:

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"student@skku.edu","password":"password123"}'

curl http://localhost:8000/api/auth/me \
  -H "Authorization: Bearer <access_token>"
```

Windows PowerShell:

```powershell
$login = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/auth/login -ContentType "application/json" -Body '{"email":"student@skku.edu","password":"password123"}'
Invoke-RestMethod -Uri http://localhost:8000/api/auth/me -Headers @{ Authorization = "Bearer $($login.access_token)" }
```

JWT 로그아웃은 서버 상태를 바꾸지 않습니다. 클라이언트가 보관한 access token을 삭제하면 로그아웃됩니다.

## 파일 업로드 제한

`POST /api/courses/{course_id}/materials`는 `multipart/form-data`의 `file` 필드를 받습니다. 관리자는 모든 과목, 교수자는 자기 담당 과목만 업로드·삭제할 수 있습니다. 학생은 접근 가능한 과목의 목록은 볼 수 있지만 업로드와 삭제는 403입니다.

| 항목 | 현재 동작 |
| --- | --- |
| 허용 확장자 | `.pdf`, `.pptx`, `.docx`, `.txt` |
| 최대 크기 | `MAX_UPLOAD_SIZE_BYTES=20971520` (20 MiB/안내상 20MB) |
| 빈 파일 | HTTP 422로 거절 |
| 허용되지 않은 확장자·최대 크기 초과 | HTTP 422로 거절 |
| 업로드 요청 본문 한도 초과 | HTTP 413으로 파싱 완료 전에 거절 |
| 내부 파일명 | 원본 확장자를 유지한 UUID 파일명 (`<uuid>.<ext>`) |
| 기본 저장 위치 | 저장소 루트에서 API를 실행할 때 `uploads/<course_id>/<uuid>.<ext>` |
| 원본 파일명 | 표시용 `originalFileName` 메타데이터로 보존, 내부 경로는 API에 노출하지 않음 |
| 새 자료 상태 | DB 내부 `processing_status=pending`, API 응답 `processingStatus: "pending"` |

성공한 업로드는 HTTP **202 Accepted**를 반환합니다. 자료의 실제 파일 저장과 DB 행 생성은 완료되지만, 이 상태는 문서 내용이 처리되었다는 뜻이 아니라 3단계 처리를 기다린다는 뜻입니다. 파일 저장 후 DB 커밋에 실패하면 저장된 파일은 제거됩니다. 운영 환경의 리버스 프록시도 `MAX_UPLOAD_REQUEST_SIZE_BYTES`와 일치하는 요청 본문 한도를 적용해 과도한 업로드를 애플리케이션에 도달하기 전에 차단하세요.

## 자동 테스트

아래 명령은 의존성 설치 후 저장소 루트에서 실행합니다. 백엔드와 RAG 테스트는 Docker DB 없이도 실행되도록 구성되어 있지만, 수동 통합 검증에는 실행 중인 PostgreSQL과 두 개 서버가 필요합니다.

Linux/macOS:

```bash
source .venv/bin/activate
make test-api
make test-rag
npm run test --workspace @skku-course-agent/frontend
npm run typecheck --workspaces --if-present
npm run lint
npm run build:frontend
```

Windows PowerShell:

```powershell
& .\.venv\Scripts\python.exe -m pytest apps/backend/tests
& .\.venv\Scripts\python.exe -m pytest packages/ai_rag/tests
npm.cmd run test --workspace @skku-course-agent/frontend
npm.cmd run typecheck --workspaces --if-present
npm.cmd run lint
npm.cmd run build:frontend
```

## 2단계 수동 통합 테스트 체크리스트

시작 전에 PostgreSQL, 마이그레이션, Seed, API(8000), 웹(3000)을 모두 실행합니다. 아래 체크는 의도적으로 데이터 상태를 바꿀 수 있으므로, 마지막의 재활성화와 임시 과목 정리를 확인합니다.

### 인증과 공통 권한

- [ ] 세 Seed 계정 `admin@skku.edu`, `professor@skku.edu`, `student@skku.edu`가 모두 `password123`으로 로그인되고 각각 `/admin`, `/professor`, `/student`로 이동한다.
- [ ] 로그인 응답의 access token으로 `GET /api/auth/me`가 200과 현재 사용자 정보를 반환한다.
- [ ] 토큰 없이 인증 API를 호출하면 401이고, 잘못된 Bearer 토큰도 401이다.
- [ ] 학생 또는 교수자가 `/admin`을 직접 열면 `/forbidden`으로 이동하며, `/api/admin/courses`는 403이다.

### 관리자

- [ ] 관리자 `/admin/courses`에서 Seed 과목 두 개를 확인하고 `/admin/courses/new`에서 담당 교수를 선택해 임시 과목을 생성한다.
- [ ] 생성한 과목의 이름 또는 설명을 수정한 뒤 목록과 상세에 반영됨을 확인한다.
- [ ] 과목을 비활성화했다가 다시 활성화하고, 두 요청이 각각 정상 응답을 반환함을 확인한다.
- [ ] 관리자 토큰으로 `GET /api/admin/users` 및 `GET /api/admin/courses/{course_id}/access`가 접근 가능한지 확인한다.

### 교수자

- [ ] 교수자 `/professor/courses`에는 본인 담당 과목만 표시되고, Seed의 두 과목이 보인다.
- [ ] 교수자 `/professor/materials`에서 담당 과목을 선택해 20MB 이하의 `.txt`, `.pdf`, `.pptx`, `.docx` 중 하나를 업로드한다. 네트워크 응답은 201이고 화면 상태는 처리 대기(`processingStatus: "pending"`)이다.
- [ ] 새 자료가 목록에 원본 파일명·형식·크기와 함께 표시되고, 새로고침 뒤에도 `GET /api/courses/{course_id}/materials`에서 보인다.
- [ ] 교수자가 업로드한 자료를 삭제하면 응답이 204이고 목록에서 사라진다.
- [ ] 교수자가 자기 담당이 아닌 과목 ID로 과목 조회·자료 목록·업로드·삭제를 시도하면 403이다.

### 학생과 과목 접근

- [ ] 학생 `/student/courses`에는 Seed의 활성 수강 과목인 인공지능개론, 소프트웨어공학만 표시된다.
- [ ] 관리자가 학생 수강 과목 하나를 비활성화하면 학생 목록에서 즉시 제외되고, 다시 활성화하면 목록에 다시 나타난다.
- [ ] 학생은 수강 중인 활성 과목의 자료 목록을 조회할 수 있지만, 같은 과목의 자료 업로드와 삭제 API는 403이다.
- [ ] 학생이 수강하지 않은 과목 ID를 `GET /api/courses/{course_id}`로 직접 요청하면 403이다.

### 파일 검증과 정리

- [ ] `.exe` 등 허용되지 않은 확장자, 빈 파일, 파일 한도를 조금 초과한 파일을 API에 업로드하면 각각 422이고 성공 자료 행이나 저장 파일이 남지 않는다. multipart 요청 본문 한도까지 초과하면 413이다.
- [ ] 성공 파일의 서버 내부 이름은 원본명과 다른 UUID이며, 저장 위치가 `uploads/<course_id>/` 아래임을 확인한다. API 응답에는 내부 파일명과 저장 경로가 노출되지 않는다.
- [ ] 과목 삭제 API는 아직 없으므로 수동 검증에는 일회용 DB를 사용하거나 임시 과목을 비활성화한다. 업로드한 임시 자료는 삭제하고, 비활성화했던 Seed 과목은 다시 활성화한다.

## 아직 구현되지 않은 기능

다음은 2단계의 의도적인 범위 밖이며, 현재 API·화면의 문구나 빈 응답을 실제 기능으로 해석하면 안 됩니다.

- native pgvector 컬럼·인덱스를 사용하는 DB 내부 벡터 검색
- 과목별 RAG 검색 HTTP API와 검색 테스트 UI
- 챗봇의 실제 답변 생성과 과제·시험 SAFE 가드레일
- 출처(citation) 기반 답변
- 채팅 세션·로그의 영속 저장과 관리자 로그/통계 대시보드

## 3단계 연결 지점

3단계 문서 처리기는 새 자료의 `pending` 상태를 읽어 `processing`으로 바꾸고, 파싱, 청크 분할, 임베딩 저장을 수행합니다. 성공하면 `completed`, 실패하면 `failed`와 `processing_error`를 기록합니다. 현재 벡터 검색은 `course_id`로 DB 후보를 먼저 제한한 뒤 애플리케이션에서 cosine 유사도를 계산하는 MVP local 방식입니다.

현재 업로드 API의 책임은 파일 저장과 `CourseMaterial` 메타데이터 생성까지입니다. 문서 내용을 해석하거나 벡터 검색을 수행하지 않으므로, 이후 동기 처리, 백그라운드 워커 또는 메시지 큐를 선택해도 현재의 업로드 계약, `course_id` 권한 규칙, `processingStatus` 응답 계약을 유지할 수 있습니다.
