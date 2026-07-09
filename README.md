# SKKU Course Agent MVP

성균관대학교 AI중심대학사업의 강의자료 기반 RAG 챗봇 MVP입니다. 학생은 과목을 선택해 질문하고, 교수자는 강의자료를 업로드하며, 관리자는 과목/사용자/로그/통계를 관리하는 구조로 확장할 수 있게 설계했습니다.

## 기술 스택

- Frontend: Next.js + TypeScript
- Backend: FastAPI + SQLAlchemy
- Database: PostgreSQL
- Vector DB: pgvector 우선, 로컬 인메모리 벡터 저장소는 개발/테스트용
- AI/RAG: 독립 Python 패키지, OpenAI API 연결 가능

## 폴더 구조

```text
.
├── apps
│   ├── backend          # FastAPI API 서버
│   └── frontend         # Next.js 웹 앱
├── packages
│   ├── ai_rag           # 임베딩, 검색, 생성 RAG 모듈
│   └── shared           # 공통 TypeScript 타입 및 JSON Schema
├── infra
│   └── postgres         # pgvector 초기화 스크립트
├── docs                 # 아키텍처 문서
├── docker-compose.yml
├── Makefile
└── .env.example
```

## 환경변수

```bash
cp .env.example .env
```

주요 값:

- `DATABASE_URL`: PostgreSQL 연결 문자열
- `OPENAI_API_KEY`: OpenAI API 키
- `JWT_SECRET`: JWT 서명용 비밀값
- `VECTOR_DB_PROVIDER`: `pgvector` 또는 `local`
- `VECTOR_DB_URL`: 벡터 저장소 연결 문자열
- `VECTOR_DB_COLLECTION`: 벡터 컬렉션/테이블 이름
- `VECTOR_DB_EMBEDDING_DIM`: 임베딩 차원

## 로컬 실행

### 1. PostgreSQL 실행

```bash
docker compose up -d db
```

또는:

```bash
make dev-db
```

### 2. Backend 실행

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e packages/ai_rag
pip install -e "apps/backend[dev]"
uvicorn app.main:app --reload --app-dir apps/backend --host 0.0.0.0 --port 8000
```

확인:

```bash
curl http://localhost:8000/api/health
```

API 문서:

```text
http://localhost:8000/docs
```

### 3. Frontend 실행

```bash
npm install
npm run dev:frontend
```

웹 앱:

```text
http://localhost:3000
```

## 테스트

```bash
cd apps/backend && pytest
cd ../../packages/ai_rag && pytest
npm run typecheck --workspaces --if-present
```

또는:

```bash
make test-api
make test-rag
make typecheck-web
```

## 현재 포함된 기본 API

- `GET /api/health`
- `GET /api/courses`
- `POST /api/courses`
- `GET /api/courses/{course_id}/materials`
- `POST /api/courses/{course_id}/materials`
- `POST /api/chat/sessions`
- `POST /api/chat/sessions/{session_id}/messages`
- `GET /api/admin/stats`

## 다음 단계

1. Alembic 마이그레이션 추가 및 SQLAlchemy 모델을 실제 DB 테이블로 생성
2. 사용자 인증/JWT, 역할 기반 접근 제어 구현
3. 강의자료 업로드 저장소와 텍스트 추출 파이프라인 구현
4. pgvector 테이블/인덱스 및 course-scoped similarity search 구현
5. OpenAI 임베딩/답변 생성 연결과 citation 포맷 확정
6. 채팅 세션/로그 저장, 관리자 통계 집계
7. 프론트엔드 API 연동, 교수자/관리자 화면 분리
