# 기술 명세서: SKKU AI중심대학사업 코스 에이전트 MVP

## 1. 문서 개요

| 항목        | 내용                                                                                |
| ----------- | ----------------------------------------------------------------------------------- |
| 프로젝트명  | SKKU 코스 에이전트 MVP                                                              |
| 목적        | 강의자료 기반 RAG 챗봇 서비스 구축                                                  |
| 주요 사용자 | 학생, 교수자, 관리자                                                                |
| 핵심 기능   | 강의자료 업로드, 문서 처리, RAG 질의응답, 출처 표시, 역할 기반 권한 관리, 로그 저장 |
| 개발 방식   | MVP 우선 구현 후 단계적 고도화                                                      |
| 개발 기간   | 2026년 7월 ~ 2026년 12월                                                            |
| 개발 인력   | Frontend 1명, Backend 1명, AI/RAG 1명                                               |

### 1.1 현재 구현 기준

2026-07-28 기준으로 검색 가능한 지식베이스까지 구현되어 있다.

- TXT, PDF, DOCX, PPTX 텍스트 추출
- 1,000자 청크와 150자 중첩
- deterministic local hash embedding
- PostgreSQL JSON embedding 저장과 애플리케이션 cosine 검색
- 과목 권한 및 `course_id` 범위가 강제되는 검색 API
- 교수자 자료 처리 UI와 RAG 검색 디버그 UI

LLM 답변 생성, citation 조립, SAFE 정책과 ChatLog 영속화는 4단계 범위다. pgvector 확장은 활성화되어 있지만 현재 vector 컬럼과 DB 거리 연산은 사용하지 않는다.

---

## 2. 시스템 목표

코스 에이전트는 교수자가 업로드한 강의자료, 교안, FAQ, 과제 설명 등을 기반으로 학생의 질문에 답변하는 교육용 AI 챗봇이다.

초기 MVP의 핵심 목표는 다음과 같다.

1. 교수자가 과목별 강의자료를 업로드할 수 있다.
2. 업로드된 문서를 텍스트로 추출하고 청크 단위로 분할한다.
3. 문서 청크를 임베딩하여 검색 가능한 지식베이스로 구축한다.
4. 학생은 접근 가능한 과목을 선택하고 질문할 수 있다.
5. 시스템은 해당 과목의 자료에서 관련 내용을 검색한다.
6. LLM은 검색 결과를 기반으로 답변을 생성한다.
7. 답변에는 사용된 강의자료 출처를 함께 표시한다.
8. 질문, 답변, 참조 문서, 사용 시간 등을 로그로 저장한다.
9. 관리자와 교수자는 사용 현황과 로그를 확인할 수 있다.

---

## 3. 전체 시스템 아키텍처

## 3.1 논리 아키텍처

```text id="2r7k9n"
[Client / Frontend]
  ├─ 학생 화면
  ├─ 교수자 화면
  └─ 관리자 화면

        ↓ REST API

[Backend API Server]
  ├─ 인증 / 인가
  ├─ 사용자 관리
  ├─ 과목 관리
  ├─ 자료 업로드 관리
  ├─ 채팅 세션 관리
  ├─ 로그 관리
  └─ 통계 API

        ↓ Internal API 또는 Service Call

[AI / RAG Service]
  ├─ 문서 파싱
  ├─ 텍스트 청크 분할
  ├─ 임베딩 생성
  ├─ 벡터 검색
  ├─ 프롬프트 구성
  ├─ LLM 답변 생성
  └─ SAFE 가드레일 적용

        ↓

[Storage Layer]
  ├─ PostgreSQL: 사용자, 과목, 로그, 권한
  ├─ File Storage: 업로드된 원본 강의자료
  └─ Vector Store: 문서 임베딩
```

---

## 3.2 물리 아키텍처

MVP에서는 관리 복잡도를 줄이기 위해 다음과 같이 구성한다.

```text id="qr411x"
Frontend: Next.js
Backend: FastAPI 또는 Node.js API Server
Database: PostgreSQL
Vector DB: pgvector 우선 검토
File Storage: Local Storage
AI Provider: Alibaba Cloud Model Studio Qwen API
Auth: JWT 기반 인증
Deployment: Docker / Docker Compose
```

향후 운영 단계에서는 다음으로 확장 가능하다.

```text id="nuk2fn"
File Storage: Local Storage → S3 호환 Object Storage
Vector DB: pgvector → 전용 Vector DB
Auth: 자체 JWT → 학교 SSO / I-Campus 연동
Backend: 단일 API 서버 → API 서버 + RAG Worker 분리
```

---

## 4. 기술 스택 제안

| 영역         | 기술                          | 설명                                |
| ------------ | ----------------------------- | ----------------------------------- |
| Frontend     | Next.js, TypeScript           | 역할별 웹 UI                        |
| Styling      | Tailwind CSS 또는 CSS Modules | 빠른 MVP UI 개발                    |
| Backend      | FastAPI 또는 Node.js/NestJS   | REST API 서버                       |
| DB           | PostgreSQL                    | 사용자, 과목, 로그, 메타데이터 저장 |
| ORM          | Prisma / SQLAlchemy           | 선택한 백엔드에 맞춰 사용           |
| Vector DB    | pgvector                      | PostgreSQL 기반 벡터 검색           |
| AI API       | Alibaba Cloud Model Studio    | Qwen LLM 답변 생성                  |
| Auth         | JWT                           | MVP 인증                            |
| File Storage | Local Storage                 | 업로드 파일 저장                    |
| Deployment   | Docker Compose                | 로컬 및 서버 배포                   |
| Test         | Jest / Pytest                 | API 및 권한 테스트                  |

---

## 5. 주요 모듈 구성

## 5.1 Frontend 모듈

### 학생 모듈

기능:

- 로그인
- 접근 가능한 과목 목록 조회
- 과목 상세 조회
- 챗봇 질의응답
- 답변 출처 확인
- 최근 대화 이력 확인

주요 화면:

```text id="f5a3vv"
/login
/student
/student/courses
/student/courses/[courseId]
/student/courses/[courseId]/chat
/student/chat-history
```

---

### 교수자 모듈

기능:

- 담당 과목 조회
- 강의자료 업로드
- 업로드 자료 목록 확인
- 자료 처리 상태 확인
- 과목별 질문 로그 조회
- 기본 응답 정책 설정

주요 화면:

```text id="krumqd"
/professor
/professor/courses
/professor/courses/[courseId]
/professor/courses/[courseId]/materials
/professor/courses/[courseId]/logs
/professor/courses/[courseId]/settings
```

---

### 관리자 모듈

기능:

- 전체 과목 관리
- 사용자 관리
- 권한 관리
- 자료 관리
- 전체 로그 조회
- 기본 통계 확인

주요 화면:

```text id="e5pwba"
/admin
/admin/courses
/admin/courses/new
/admin/courses/[courseId]
/admin/users
/admin/materials
/admin/logs
/admin/statistics
```

---

## 5.2 Backend 모듈

```text id="wmgo7i"
backend/
├── auth/
│   ├── login
│   ├── jwt
│   └── current-user
├── users/
│   ├── user-service
│   └── role-service
├── courses/
│   ├── course-service
│   ├── enrollment-service
│   └── permission-service
├── materials/
│   ├── upload-service
│   ├── file-storage-service
│   └── material-service
├── rag/
│   ├── document-parser
│   ├── chunker
│   ├── embedding-service
│   ├── vector-search-service
│   └── answer-generation-service
├── chat/
│   ├── chat-session-service
│   ├── chat-log-service
│   └── chat-controller
├── statistics/
│   └── statistics-service
└── common/
    ├── error-handler
    ├── validation
    └── config
```

---

## 6. 사용자 역할 및 권한 정책

## 6.1 역할 정의

| 역할      | 설명                               |
| --------- | ---------------------------------- |
| student   | 과목별 챗봇을 사용하는 학생        |
| professor | 담당 과목과 자료를 관리하는 교수자 |
| admin     | 전체 서비스 운영 관리자            |

---

## 6.2 권한 정책

| 기능                |     Student |   Professor | Admin |
| ------------------- | ----------: | ----------: | ----: |
| 로그인              |           O |           O |     O |
| 내 과목 조회        |           O |           O |     O |
| 전체 과목 조회      |           X |           X |     O |
| 과목 생성           |           X |           X |     O |
| 과목 수정           |           X |           X |     O |
| 과목 비활성화       |           X |           X |     O |
| 담당 과목 조회      |           X |           O |     O |
| 강의자료 업로드     |           X | 담당 과목만 |     O |
| 자료 삭제           |           X | 담당 과목만 |     O |
| 학생 챗봇 사용      | 접근 과목만 | 선택적 허용 |     O |
| 본인 대화 이력 조회 |           O |           O |     O |
| 과목 질문 로그 조회 |           X | 담당 과목만 |     O |
| 전체 로그 조회      |           X |           X |     O |
| 통계 조회           |      제한적 | 담당 과목만 |     O |

---

## 6.3 과목 접근 정책

### 학생

학생은 `CourseEnrollment` 또는 `CourseAccess`에 등록된 활성 과목만 조회할 수 있다.

조건:

```text id="qgtf6t"
course.is_active = true
AND course_access.user_id = current_user.id
```

### 교수자

교수자는 본인이 담당 교수자로 등록된 과목만 관리할 수 있다.

조건:

```text id="c6cw9n"
course.professor_id = current_user.id
```

### 관리자

관리자는 모든 과목, 사용자, 자료, 로그에 접근할 수 있다.

---

## 7. 데이터베이스 설계

## 7.1 User

사용자 계정 정보를 저장한다.

| 필드          | 타입           | 설명                        |
| ------------- | -------------- | --------------------------- |
| id            | UUID / BIGINT  | 사용자 ID                   |
| name          | VARCHAR        | 이름                        |
| email         | VARCHAR UNIQUE | 이메일                      |
| password_hash | VARCHAR        | 비밀번호 해시               |
| school_id     | VARCHAR NULL   | 학번 또는 교직원 번호       |
| role          | ENUM           | student / professor / admin |
| created_at    | TIMESTAMP      | 생성 시각                   |
| updated_at    | TIMESTAMP      | 수정 시각                   |

---

## 7.2 Course

과목 정보를 저장한다.

| 필드         | 타입          | 설명        |
| ------------ | ------------- | ----------- |
| id           | UUID / BIGINT | 과목 ID     |
| name         | VARCHAR       | 과목명      |
| semester     | VARCHAR       | 학기        |
| description  | TEXT          | 과목 설명   |
| professor_id | FK(User.id)   | 담당 교수자 |
| is_active    | BOOLEAN       | 활성화 여부 |
| created_at   | TIMESTAMP     | 생성 시각   |
| updated_at   | TIMESTAMP     | 수정 시각   |

---

## 7.3 CourseAccess

학생의 과목 접근 권한을 저장한다.

| 필드        | 타입          | 설명                      |
| ----------- | ------------- | ------------------------- |
| id          | UUID / BIGINT | 접근 권한 ID              |
| course_id   | FK(Course.id) | 과목 ID                   |
| user_id     | FK(User.id)   | 사용자 ID                 |
| access_role | VARCHAR       | student / ta 등 확장 가능 |
| created_at  | TIMESTAMP     | 생성 시각                 |

제약 조건:

```text id="pph3ck"
UNIQUE(course_id, user_id)
```

---

## 7.4 CourseMaterial

업로드된 강의자료 메타데이터를 저장한다.

| 필드               | 타입          | 설명                                      |
| ------------------ | ------------- | ----------------------------------------- |
| id                 | UUID / BIGINT | 자료 ID                                   |
| course_id          | FK(Course.id) | 과목 ID                                   |
| week               | SMALLINT      | 게시 주차(1~16), 기본값 1                 |
| uploaded_by        | FK(User.id)   | 업로드 사용자                             |
| file_name          | VARCHAR       | 내부 저장 파일명                          |
| original_file_name | VARCHAR       | 원본 파일명                               |
| file_type          | VARCHAR       | 파일 확장자                               |
| file_size          | BIGINT        | 파일 크기                                 |
| storage_path       | TEXT          | 저장 경로                                 |
| processing_status  | ENUM          | pending / processing / completed / failed |
| processing_error   | TEXT NULL     | 처리 실패 사유                            |
| created_at         | TIMESTAMP     | 업로드 시각                               |
| updated_at         | TIMESTAMP     | 수정 시각                                 |

---

## 7.5 DocumentChunk

문서에서 추출된 청크 정보를 저장한다.

| 필드          | 타입                  | 설명                      |
| ------------- | --------------------- | ------------------------- |
| id            | UUID / BIGINT         | 청크 ID                   |
| course_id     | FK(Course.id)         | 과목 ID                   |
| material_id   | FK(CourseMaterial.id) | 원본 자료 ID              |
| chunk_index   | INT                   | 청크 순서                 |
| chunk_text    | TEXT                  | 청크 내용                 |
| page_number   | INT NULL              | 페이지 또는 슬라이드 번호 |
| section_title | VARCHAR NULL          | 섹션명                    |
| char_count    | INT                   | 청크 글자 수              |
| embedding     | JSON NULL             | 임베딩 벡터               |
| embedding_model | VARCHAR NULL        | 임베딩 모델명             |
| embedded_at   | TIMESTAMP NULL        | 임베딩 생성 시각          |
| created_at    | TIMESTAMP             | 생성 시각                 |
| updated_at    | TIMESTAMP             | 수정 시각                 |

인덱스:

```text id="vjfys3"
INDEX(course_id)
INDEX(material_id)
UNIQUE(material_id, chunk_index)
```

**구현 현황 (2026-08 기준)**

- `embedding`은 pgvector `VECTOR`가 아니라 이식 가능한 `JSON` 컬럼으로 구현했다. 검색은 `VECTOR_SEARCH_MODE=local`에서 애플리케이션 레벨 코사인 유사도로 수행한다. 개발 규모용 구현이며, pgvector 전환 시 `VectorStoreService`만 교체하면 된다.
- 따라서 벡터 인덱스는 아직 생성하지 않는다.
- `UNIQUE(material_id, chunk_index)`로 재처리 시 중복 저장을 막는다.

---

## 7.6 ChatSession

대화 세션 정보를 저장한다.

| 필드       | 타입          | 설명      |
| ---------- | ------------- | --------- |
| id         | UUID / BIGINT | 세션 ID   |
| user_id    | FK(User.id)   | 사용자 ID |
| course_id  | FK(Course.id) | 과목 ID   |
| title      | VARCHAR NULL  | 세션 제목 |
| created_at | TIMESTAMP     | 생성 시각 |
| updated_at | TIMESTAMP     | 수정 시각 |

---

## 7.7 ChatLog

질문과 답변 로그를 저장한다.

| 필드                 | 타입               | 설명               |
| -------------------- | ------------------ | ------------------ |
| id                   | UUID / BIGINT      | 로그 ID            |
| session_id           | FK(ChatSession.id) | 세션 ID            |
| user_id              | FK(User.id)        | 사용자 ID          |
| course_id            | FK(Course.id)      | 과목 ID            |
| question             | TEXT               | 사용자 질문        |
| answer               | TEXT               | AI 답변            |
| referenced_documents | JSON               | 참조 문서 목록     |
| model_name           | VARCHAR NULL       | 사용 모델          |
| retrieval_result     | JSON               | 검색 요약 정보     |
| response_time_ms     | INT NULL           | 응답 시간          |
| is_grounded          | BOOLEAN            | 강의자료 근거 여부 |
| answer_source_type   | ENUM               | rag / general_llm / safety_response / no_material |
| safety_result        | JSON               | SAFE 가드레일 결과 |
| created_at           | TIMESTAMP          | 생성 시각          |

**구현 현황 (2026-08 기준)**

- 명세의 `retrieval_score`는 `retrieval_result`로 구현했고 `top_k`, `result_count`, `max_score`, `score_threshold`, `search_mode`, `embedding_model`, `total_candidate_chunks`, `reason`을 담는다.
- 답변 근거 구분을 위해 `is_grounded`와 `answer_source_type`을 추가했다.
- SQLite 테스트 호환을 위해 `JSONB` 대신 이식 가능한 `JSON` 타입을 사용한다.
- LLM 호출이 실패한 요청은 로그로 저장하지 않는다. 저장되는 로그는 사용자에게 실제로 반환된 답변(안전 응답 포함)만이다.

---

## 8. API 명세

## 8.1 인증 API

### POST /auth/login

로그인 API.

Request:

```json id="9z971d"
{
  "email": "student@skku.edu",
  "password": "password123"
}
```

Response:

```json id="ee0obs"
{
  "access_token": "jwt-token",
  "token_type": "bearer",
  "user": {
    "id": "user-id",
    "name": "Student",
    "email": "student@skku.edu",
    "role": "student"
  }
}
```

---

### GET /auth/me

현재 로그인한 사용자 조회.

Headers:

```text id="j52wpg"
Authorization: Bearer <access_token>
```

Response:

```json id="z2agsz"
{
  "id": "user-id",
  "name": "Student",
  "email": "student@skku.edu",
  "role": "student"
}
```

---

## 8.2 관리자 과목 API

### GET /admin/courses

전체 과목 목록 조회.

권한:

```text id="buwtnu"
admin
```

Query Parameters:

| 이름         | 설명        |
| ------------ | ----------- |
| semester     | 학기 필터   |
| is_active    | 활성화 여부 |
| professor_id | 교수자 ID   |
| keyword      | 검색어      |

---

### POST /admin/courses

과목 생성.

권한:

```text id="nkp88a"
admin
```

Request:

```json id="as3vlo"
{
  "name": "인공지능개론",
  "semester": "2026-2",
  "description": "AI 기본 개념을 학습하는 과목",
  "professor_id": "professor-user-id",
  "is_active": true
}
```

---

### PATCH /admin/courses/{course_id}

과목 수정.

권한:

```text id="e1ed73"
admin
```

---

### PATCH /admin/courses/{course_id}/activate

과목 활성화.

권한:

```text id="9dcjwl"
admin
```

---

### PATCH /admin/courses/{course_id}/deactivate

과목 비활성화.

권한:

```text id="7qdggf"
admin
```

---

## 8.3 교수자 API

### GET /professor/courses

담당 과목 목록 조회.

권한:

```text id="o6jvdy"
professor, admin
```

동작:

- professor: 본인 담당 과목만 반환
- admin: 전체 또는 특정 교수자 과목 반환 가능

---

### GET /courses/{course_id}/materials

과목 자료 목록 조회.

권한:

```text id="a44l93"
professor: 본인 담당 과목
admin: 전체 과목
student: 본인이 수강 중인 활성 과목
```

---

### POST /courses/{course_id}/materials

강의자료 업로드.

권한:

```text id="k2uypc"
professor: 본인 담당 과목
admin: 전체 과목
```

Request:

```text id="65ralt"
multipart/form-data
file: 강의자료 파일
week: 게시 주차(1~16, 기본값 1)
```

Response:

```json id="s27w37"
{
  "id": "material-id",
  "course_id": "course-id",
  "week": 1,
  "original_file_name": "lecture1.pdf",
  "file_type": "pdf",
  "file_size": 1048576,
  "processing_status": "completed",
  "created_at": "2026-07-01T10:00:00"
}
```

---

### GET /courses/{course_id}/materials/{material_id}/download

강의자료 원본 다운로드. 자료 목록 조회와 동일한 과목 접근 권한을 적용한다.

---

### DELETE /courses/{course_id}/materials/{material_id}

강의자료 삭제.

권한:

```text id="818nzt"
professor: 본인 담당 과목
admin: 전체 과목
```

---

## 8.4 학생 API

### GET /student/courses

학생이 접근 가능한 과목 목록 조회.

권한:

```text id="4hjeir"
student
```

동작:

- 현재 로그인한 학생이 접근 가능한 과목만 반환
- `is_active = true`인 과목만 반환

---

### GET /student/courses/{course_id}

학생 과목 상세 조회.

권한:

```text id="8aimas"
student
```

동작:

- 학생이 접근 가능한 활성 과목만 조회 가능
- 접근 권한 없으면 403 또는 404 반환

---

## 8.5 RAG 검색 API

### POST /api/rag/search

질문에 대한 관련 문서 청크 검색.

권한:

```text id="2cy22h"
student: 수강 중인 활성 과목
professor: 본인 담당 과목
admin: 모든 과목
```

Request:

```json id="m1h4c7"
{
  "course_id": "course-id",
  "question": "경사하강법이 뭐야?",
  "top_k": 5
}
```

Response:

```json id="t2m54s"
{
  "course_id": "course-id",
  "question": "경사하강법이 뭐야?",
  "top_k": 5,
  "results": [
    {
      "chunk_id": "chunk-id",
      "material_id": "material-id",
      "document_name": "lecture1.pdf",
      "page_number": 12,
      "chunk_index": 3,
      "chunk_text": "경사하강법은...",
      "score": 0.87
    }
  ],
  "debug": null
}
```

**구현 현황 (2026-08 기준)**

- 실제 엔드포인트는 `POST /api/rag/search`이며, 요청/응답 필드는 camelCase(`courseId`, `topK`, `documentName`, `pageNumber`, `chunkIndex`)로 직렬화된다.
- 응답에는 `courseId`, `question`, `topK`가 함께 포함되고, 각 결과에 `chunkIndex`가 추가된다.
- 요청에 `debug: true`를 넣으면 `embeddingModel`, `searchMode`, `scoreThreshold`, `totalCandidateChunks`가 담긴 `debug` 객체가 반환된다.
- `topK`는 `RAG_TOP_K`가 기본값이고 `RAG_MAX_TOP_K`로 상한이 걸린다. 검색은 항상 `course_id`로 먼저 제한된다.
- `debug=true`는 교수자와 관리자만 사용할 수 있으며 검색 API 자체는 답변을 생성하지 않는다.

### 자료 처리 API (구현 추가분)

명세에 없었지만 3단계 파이프라인 실행을 위해 다음 엔드포인트를 추가했다.

```text
POST /api/courses/{course_id}/materials/{material_id}/process
POST /api/courses/{course_id}/materials/{material_id}/reprocess
GET  /api/courses/{course_id}/materials/{material_id}/processing-status
GET  /api/courses/{course_id}/rag/status
```

권한은 과목 관리 권한(교수자는 담당 과목, 관리자는 전체)을 따르며, `rag/status`만 과목 접근 권한으로 충분하다. 이미 처리 중인 자료에 process를 다시 호출하면 409를 반환한다.

### GET /api/courses/{course_id}/rag/status

자료 처리 수, 전체/임베딩 청크 수와 검색 준비 상태를 반환한다. 완료된 자료에 임베딩 청크가 하나 이상 있을 때 `is_search_ready=true`다.

---

## 8.6 챗봇 API

### POST /chat (4단계 Roadmap)

과목별 RAG 기반 답변 생성.

권한:

```text id="ivoyr0"
해당 과목 접근 권한 필요
```

Request:

```json id="xvjzul"
{
  "course_id": "course-id",
  "question": "경사하강법이 뭐야?",
  "chat_session_id": "optional-session-id"
}
```

처리 흐름:

```text id="wcse31"
1. 사용자 인증 확인
2. 과목 접근 권한 확인
3. SAFE 가드레일 검사
4. 질문 임베딩 생성
5. 관련 문서 청크 검색
6. 프롬프트 구성
7. LLM 답변 생성
8. 출처 목록 생성
9. ChatLog 저장
10. 답변 반환
```

Response:

```json id="gmq7kd"
{
  "answer": "경사하강법은 손실 함수를 줄이는 방향으로 파라미터를 반복적으로 업데이트하는 최적화 방법입니다...",
  "sources": [
    {
      "material_id": "material-id",
      "document_name": "lecture1.pdf",
      "page_number": 12,
      "chunk_index": 3
    }
  ],
  "is_grounded": true,
  "session_id": "chat-session-id"
}
```

**구현 현황 (2026-08 기준)**

- 실제 엔드포인트는 `POST /api/chat`이고, 필드는 camelCase로 직렬화된다.
- 응답에는 위 필드에 더해 `logId`, `answerSourceType`, `modelName`, `responseTimeMs`, `retrievalSummary`, `safety`, 각 출처의 `score`가 포함된다.
- `answerSourceType`으로 `rag` / `general_llm` / `safety_response` / `no_material`을 구분한다.
- 출처는 LLM 출력이 아니라 서버가 검색 결과에서 만들고, `(material_id, page_number, chunk_index)` 기준으로 중복을 제거한다.
- 근거가 부족하면 `sources`는 빈 배열이고 답변 앞에 자료 부족 안내가 붙는다.
- 오류 코드: 인증 없음 401, 과목 권한 없음 403, 세션 없음 404, 질문 검증 실패 422, 검색·생성 실패 503(`RAG_SEARCH_FAILED` / `LLM_GENERATION_FAILED`).

---

## 8.7 로그 API

### GET /student/chat-logs

학생 본인 대화 이력 조회.

권한:

```text id="3zj9x9"
student
```

**구현 현황 (2026-08 기준)**

세션 단위 조회로 구현했다.

```text
GET    /api/student/chat-sessions           # 본인 세션 목록
GET    /api/student/chat-sessions/{id}      # 세션 상세와 질문/답변 로그
GET    /api/chat/sessions                   # 역할 무관, 본인 세션 목록
POST   /api/chat/sessions                   # 세션 생성
GET    /api/chat/sessions/{id}              # 세션 상세
PATCH  /api/chat/sessions/{id}              # 세션 제목 수정
DELETE /api/chat/sessions/{id}              # 세션 삭제
```

세션 제목은 첫 질문의 앞 40자로 자동 생성된다. 세션 상세 진입 시 소유자 확인과 과목 접근 권한을 다시 검사하므로, 수강이 취소되면 이전 대화도 열 수 없다.

---

### GET /professor/courses/{course_id}/chat-logs

교수자 담당 과목 질문 로그 조회.

권한:

```text id="v8s3ay"
professor: 본인 담당 과목
admin: 전체 과목
```

---

### GET /admin/chat-logs

전체 로그 조회.

권한:

```text id="tk4782"
admin
```

**구현 현황 (2026-08 기준)**

```text
GET /api/professor/courses/{course_id}/chat-logs
GET /api/professor/chat-logs/{log_id}
GET /api/admin/chat-logs
GET /api/admin/chat-logs/{log_id}
```

- 지원 필터: `keyword`(질문·답변 본문), `from`, `to`, `is_grounded`, `safety_category`, `limit`, `offset`. 관리자 목록은 `course_id`, `user_id`도 지원한다.
- 응답은 `{ "logs": [...], "total": n }` 형태이며, 목록에는 답변 전문 대신 120자 미리보기(`answerPreview`)만 담는다.
- 개인정보 최소화: 교수자 화면에는 학생 이메일을 마스킹한 `userLabel`만 주고 `userId`는 `null`이다. 관리자에게만 이름·이메일과 `userId`를 노출한다.
- 교수자는 담당 과목이 아닌 로그를 목록·상세 어느 쪽으로도 조회할 수 없다(403).
- CSV 내보내기는 5단계로 남긴다.

---

## 8.8 통계 API

### GET /admin/statistics

전체 서비스 통계 조회.

권한:

```text id="hkug25"
admin
```

Response 예시:

```json id="oj078k"
{
  "total_users": 120,
  "total_courses": 8,
  "total_questions": 3520,
  "total_materials": 95,
  "daily_questions": [
    {
      "date": "2026-07-01",
      "count": 120
    }
  ]
}
```

---

### GET /professor/statistics

교수자 담당 과목 통계 조회.

권한:

```text id="n99sw8"
professor
```

---

## 9. RAG 파이프라인 명세

## 9.1 문서 업로드 흐름

```text id="pgmt0a"
1. 교수자가 게시 주차를 선택하고 강의자료 업로드
2. Backend가 파일 검증
3. 파일을 storage에 저장
4. CourseMaterial 생성
5. processing_status = completed
6. 학생·관리자 강의콘텐츠 목록에 즉시 게시
7. 후속 RAG 인덱싱 파이프라인이 텍스트 추출, 청크 분할, 임베딩을 수행
```

실패 시:

```text id="anxbq0"
processing_status = failed
processing_error = 실패 사유
```

---

## 9.2 지원 파일 형식

MVP 우선순위:

| 형식 | 지원 여부 | 설명                 |
| ---- | --------- | -------------------- |
| TXT  | P0        | 바로 텍스트 처리     |
| PDF  | P0        | 텍스트 추출          |
| DOCX | P1        | 고도화 또는 후순위   |
| PPTX | P1        | 슬라이드 텍스트 추출 |
| HWP  | P2        | 별도 파서 검토 필요  |

**구현 현황 (2026-08 기준)**

- TXT는 기본 의존성만으로 동작한다(UTF-8 → UTF-8 BOM → CP949 순으로 디코딩 시도).
- PDF는 `pypdf`로 페이지별 추출하며 백엔드 기본 의존성에 포함된다.
- DOCX/PPTX는 `python-docx`, `python-pptx`를 지연 임포트한다. 선택 의존성(`apps/backend[parsers]`)이며, 미설치 상태로 처리하면 `DOCUMENT_PARSER_UNAVAILABLE` 사유와 함께 `failed` 처리된다.
- HWP는 업로드 허용 확장자에 없으므로 업로드 단계에서 422로 거절된다.
- 텍스트가 전혀 추출되지 않으면 `DOCUMENT_TEXT_NOT_FOUND`로 실패 처리한다. OCR은 지원하지 않는다.

---

## 9.3 청크 분할 정책

MVP 기본값:

| 항목          | 값                                               |
| ------------- | ------------------------------------------------ |
| chunk_size    | 800 ~ 1,200 tokens                               |
| chunk_overlap | 100 ~ 200 tokens                                 |
| 기준          | 문단 우선, 불가능하면 토큰 기준                  |
| 메타데이터    | course_id, material_id, page_number, chunk_index |

**구현 현황 (2026-08 기준)**

토큰 대신 문자 수 기준으로 구현했다(`CHUNK_SIZE=1000`, `CHUNK_OVERLAP=150`). 문단을 우선 묶고, 한 문단이 `chunk_size`를 넘으면 겹침을 둔 문자 윈도로 자른다. `MIN_CHUNK_CHARS`(기본 40자)보다 짧은 청크는 같은 페이지의 앞 청크에 합친다. 재처리 시에는 해당 자료의 기존 청크를 먼저 삭제하므로 중복이 생기지 않는다.

청크 예시:

```json id="jadkv3"
{
  "course_id": "course-id",
  "material_id": "material-id",
  "chunk_index": 0,
  "chunk_text": "머신러닝은 데이터를 기반으로...",
  "page_number": 3
}
```

---

## 9.4 임베딩 정책

임베딩은 외부 API 키가 필요 없는 deterministic local hash provider를 사용한다. Qwen API는 답변 생성에만 사용하며 현재 임베딩 경로와 분리한다.

예시 모델:

```text id="ggqms5"
local-hash-128
```

저장 방식:

```text id="f80qq3"
DocumentChunk.embedding
```

로컬 임베딩은 항상 사용 가능하며 별도 API Key가 필요하지 않다.

**구현 현황 (2026-08 기준)**

- local hash 임베딩은 별도 API 키 없이 항상 사용할 수 있다.
- mock 제공자는 같은 텍스트에 항상 같은 벡터를 만든다. 공백 토큰만 쓰면 한국어의 조사 변화("경사하강법은" vs "경사하강법이")를 잡지 못하므로, 단어 토큰과 문자 2/3-gram을 함께 해싱한다. 기본 차원은 512다.
- mock 벡터의 유사도 값은 실제 모델보다 낮게 나오므로 `RAG_SCORE_THRESHOLD` 기본값을 0.1로 두었다. 실제 임베딩 모델로 바꿀 때는 0.3 수준으로 올리는 것을 권장한다.

---

## 9.5 검색 정책

검색 범위는 반드시 과목 단위로 제한한다.

조건:

```text id="u2h2e7"
DocumentChunk.course_id = selected_course_id
```

검색 기본값:

| 항목            | 값                |
| --------------- | ----------------- |
| top_k           | 5                 |
| score_threshold | 0.3               |
| 검색 방식       | local cosine      |
| 필터            | course_id 필수    |

검색 결과가 부족한 경우:

```text id="cvgsh3"
강의자료에서 직접 확인된 내용이 부족합니다.
일반적인 개념 설명은 다음과 같습니다.
```

---

## 9.6 답변 생성 프롬프트 정책 (4단계 Roadmap)

답변 생성 provider는 Alibaba Cloud Model Studio의 OpenAI 호환 Chat Completions API를 사용하며 기본 모델은 `qwen3.8-27b`이다. API 인증은 `QWEN_API_KEY`, 모델 설정은 `QWEN_MODEL`, 리전별 호환 API 주소는 `QWEN_BASE_URL`을 사용한다.

시스템 프롬프트와 대화 이력은 OpenAI 호환 `messages` 배열로 전달한다. COURSE AGENT의 도구 정의, assistant tool call, tool result도 같은 호환 형식을 사용한다. 스트리밍 응답에서는 text delta와 tool-call argument delta를 각각 누적한다.

일반 답변에는 `LLM_TEMPERATURE`와 `LLM_MAX_TOKENS`를 적용하고, 구조화 판정은 Qwen의 JSON object 응답 형식을 사용한다.

`qwen3.8-27b`은 function calling, structured output, 내장 웹 검색을 모두 지원한다. 주 답변과 에이전트 추론은 `QWEN_MODEL`을 사용하고, 신뢰 웹 검색도 기본적으로 같은 모델을 `QWEN_WEB_SEARCH_MODEL`에 지정해 DashScope native API로 호출한다. 검색 쿼리는 교수자 허용 도메인으로 제한하고, 반환된 모든 출처 URL의 호스트를 서버에서 다시 검증한다. 허용 목록 밖 출처가 하나라도 포함되면 결과 전체를 거부한다.

LLM에는 다음 정보를 전달한다.

```text id="c716b6"
- 사용자 질문
- 검색된 강의자료 청크
- 과목명
- 답변 정책
- SAFE 가드레일 규칙
```

기본 시스템 프롬프트 예시:

```text id="pnkc4w"
너는 성균관대학교 수업을 돕는 교육용 코스 에이전트다.

반드시 제공된 강의자료 컨텍스트를 우선 근거로 답변한다.
강의자료에 없는 내용은 확정적으로 말하지 않는다.
출처가 부족하면 “강의자료에서 직접 확인된 내용이 부족합니다”라고 말한다.
과제나 시험의 정답을 직접 요구하는 경우, 정답을 그대로 제공하지 말고 개념 설명, 접근 방법, 단계별 힌트를 제공한다.
학생이 스스로 이해할 수 있도록 친절하고 명확하게 답변한다.
```

---

## 10. SAFE Framework 명세

MVP에서는 초기 SAFE Framework를 적용한다.

## 10.1 출처 검증

모든 RAG 답변은 가능한 경우 출처를 포함해야 한다.

출처 정보:

```text id="n8f69f"
- 문서명
- 페이지 번호
- 청크 번호
- 자료 ID
```

출처가 없는 경우:

```text id="d0d4v7"
강의자료에서 직접 확인된 내용이 부족합니다.
```

---

## 10.2 교육 윤리 가드레일

다음 유형의 요청은 직접 수행하지 않는다.

| 요청 유형                | 처리 방식                  |
| ------------------------ | -------------------------- |
| 과제 전체 작성 요청      | 접근 방법과 힌트 제공      |
| 시험 정답 요구           | 개념 설명으로 전환         |
| 부정행위 요청            | 거절 및 학습 방향 안내     |
| 개인정보 요청            | 거절                       |
| 시스템 프롬프트 탈취     | 거절                       |
| 위험하거나 부적절한 요청 | 거절 또는 안전한 방향 전환 |

**구현 현황 (2026-08 기준)**

`SafetyGuardService`가 답변 생성 전에 질문을 분류하고, 결과를 `ChatLog.safety_result`에 저장한다. 분류 값은 `normal`, `assignment_direct_answer`, `exam_direct_answer`, `privacy_request`, `prompt_injection`, `unsafe_content`이다.

- 과제·시험 정답 요청은 차단이 아니라 `redirect_type=hint`로 표시하고, 힌트 중심 프롬프트로 답변을 생성한다(검색은 그대로 수행).
- 개인정보·프롬프트 탈취·위험 요청은 LLM 호출 없이 안전 응답을 반환하고 `answer_source_type=safety_response`로 저장한다.
- 규칙 기반(정규식) 구현이며 한국어/영어 표현을 함께 다룬다. 개념 설명, 힌트 요청, 오류 원인 분석 같은 정상 질문은 허용 목록으로 보호한다.
- LLM 기반 moderation으로 교체할 수 있도록 서비스 경계로 분리했다.

---

## 10.3 AI 사용 이력 관리

저장할 로그:

```text id="snb70x"
- 사용자 ID
- 과목 ID
- 질문
- 답변
- 참조 문서
- 모델명
- 응답 시간
- 생성 시각
- SAFE 검사 결과
```

---

## 10.4 비식별화 고려

향후 서비스 개선 및 AI 모델 고도화를 위해 로그를 활용할 수 있으나, 다음 원칙을 따른다.

```text id="dz0o1n"
- 개인정보 최소 수집
- 분석용 데이터 비식별화
- 사용자 식별 정보 제거
- 과목/질문 패턴 중심 분석
```

---

## 11. 파일 업로드 명세

## 11.1 업로드 제한

| 항목           | 정책                      |
| -------------- | ------------------------- |
| 허용 확장자    | txt, pdf, docx, pptx      |
| MVP 필수 처리  | txt, pdf                  |
| 최대 파일 크기 | 기본 20MB                 |
| 저장 방식      | UUID 기반 내부 파일명     |
| 원본 파일명    | original_file_name에 저장 |
| 저장 경로      | UPLOAD_DIR 환경변수 사용  |

---

## 11.2 파일 저장 예시

```text id="ykmvba"
uploads/
└── courses/
    └── {course_id}/
        └── {uuid}.pdf
```

---

## 11.3 처리 상태

| 상태       | 설명                          |
| ---------- | ----------------------------- |
| pending    | 업로드 완료, 아직 처리 전     |
| processing | 텍스트 추출 및 임베딩 처리 중 |
| completed  | 지식베이스 생성 완료          |
| failed     | 처리 실패                     |

---

## 12. 인증 및 보안 명세

## 12.1 인증 방식

MVP에서는 JWT 기반 인증을 사용한다.

```text id="33hrkc"
POST /auth/login
→ access_token 발급
→ 이후 API 요청에 Authorization Header 포함
```

Header:

```text id="23azcp"
Authorization: Bearer <access_token>
```

---

## 12.2 비밀번호 저장

비밀번호는 평문 저장하지 않는다.

권장 방식:

```text id="ppgx64"
bcrypt 또는 argon2 기반 password_hash 저장
```

---

## 12.3 환경변수

```text id="2b5pg4"
DATABASE_URL=
QWEN_API_KEY=
QWEN_MODEL=qwen3.8-27b
QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
QWEN_ENABLE_THINKING=false
QWEN_DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/api/v1
QWEN_WEB_SEARCH_MODEL=qwen3.8-27b
JWT_SECRET=
JWT_EXPIRES_IN=
UPLOAD_DIR=
MAX_UPLOAD_SIZE=
```

---

## 12.4 보안 정책

| 항목                 | 정책                   |
| -------------------- | ---------------------- |
| 인증되지 않은 요청   | 401                    |
| 권한 없는 요청       | 403                    |
| 존재하지 않는 리소스 | 404                    |
| 유효하지 않은 입력   | 400 또는 422           |
| 내부 서버 오류       | 500                    |
| 비밀값 관리          | 환경변수 사용          |
| 업로드 파일명        | UUID로 변환            |
| 파일 확장자 검증     | 필수                   |
| 학생 과목 접근       | CourseAccess 기준 제한 |

---

## 13. 에러 응답 형식

공통 에러 응답은 다음 형식을 사용한다.

```json id="lk05cf"
{
  "error": {
    "code": "COURSE_NOT_FOUND",
    "message": "과목을 찾을 수 없습니다."
  }
}
```

주요 에러 코드:

| 코드                       | 설명                    |
| -------------------------- | ----------------------- |
| UNAUTHORIZED               | 인증 필요               |
| FORBIDDEN                  | 권한 없음               |
| INVALID_CREDENTIALS        | 로그인 실패             |
| USER_NOT_FOUND             | 사용자 없음             |
| COURSE_NOT_FOUND           | 과목 없음               |
| COURSE_ACCESS_DENIED       | 과목 접근 권한 없음     |
| MATERIAL_NOT_FOUND         | 자료 없음               |
| INVALID_FILE_TYPE          | 허용되지 않은 파일 형식 |
| FILE_TOO_LARGE             | 파일 크기 초과          |
| FILE_UPLOAD_FAILED         | 파일 업로드 실패        |
| DOCUMENT_PROCESSING_FAILED | 문서 처리 실패          |
| RAG_SEARCH_FAILED          | RAG 검색 실패           |
| LLM_GENERATION_FAILED      | 답변 생성 실패          |

---

## 14. 프론트엔드 상태 관리

## 14.1 인증 상태

저장 정보:

```text id="l9w8h6"
- access_token
- current_user
- role
```

필요 기능:

```text id="nxe584"
- 로그인
- 로그아웃
- /auth/me로 로그인 상태 복원
- 역할별 라우트 보호
- API 요청 시 Authorization Header 자동 추가
```

---

## 14.2 역할별 라우팅

로그인 성공 후 이동 경로:

| 역할      | 기본 경로  |
| --------- | ---------- |
| student   | /student   |
| professor | /professor |
| admin     | /admin     |

---

## 14.3 UI 상태

모든 주요 화면은 다음 상태를 처리한다.

```text id="m4xv53"
- loading
- error
- empty
- success
```

예시:

```text id="c7el2p"
등록된 과목이 없습니다.
업로드된 자료가 없습니다.
접근 가능한 과목이 없습니다.
파일 업로드 중입니다.
권한이 없습니다.
```

---

## 15. 로그 및 통계 명세

## 15.1 로그 저장 기준

모든 챗봇 질문은 `ChatLog`에 저장한다.

필수 저장 항목:

```text id="w3ak2h"
- user_id
- course_id
- question
- answer
- referenced_documents
- model_name
- response_time_ms
- created_at
```

---

## 15.2 통계 지표

관리자 통계:

```text id="6e65q4"
- 전체 사용자 수
- 전체 과목 수
- 전체 질문 수
- 전체 업로드 자료 수
- 일자별 질문 수
- 과목별 질문 수
- 과목별 사용자 수
- 과목별 자료 수
```

교수자 통계:

```text id="yiyih0"
- 담당 과목별 질문 수
- 담당 과목별 사용자 수
- 담당 과목별 업로드 자료 수
- 최근 질문 로그
- 자주 등장한 질문 키워드
```

학생 통계:

```text id="95pisb"
- 본인 질문 수
- 최근 대화 이력
- 과목별 사용 기록
```

---

## 16. 배포 명세

## 16.1 로컬 개발 환경

권장 구성:

```text id="xcv8db"
Docker Compose
├── frontend
├── backend
├── postgres
└── pgvector
```

---

## 16.2 docker-compose 구성 예시

```yaml id="f73k0v"
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: course_agent
      POSTGRES_PASSWORD: course_agent
      POSTGRES_DB: course_agent
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  backend:
    build: ./backend
    env_file:
      - ./backend/.env
    ports:
      - "8000:8000"
    depends_on:
      - postgres

  frontend:
    build: ./frontend
    env_file:
      - ./frontend/.env
    ports:
      - "3000:3000"
    depends_on:
      - backend

volumes:
  postgres_data:
```

실제 레포 구조에 따라 수정 필요.

---

## 17. 테스트 명세

## 17.1 단위 테스트

대상:

```text id="bqwa21"
- 로그인 검증
- JWT 검증
- 역할 권한 체크
- 과목 접근 권한 체크
- 파일 확장자 검증
- 청크 분할 함수
- SAFE 가드레일 분류
```

---

## 17.2 API 테스트

테스트 시나리오:

```text id="iq9ajz"
1. admin 로그인
2. professor 로그인
3. student 로그인
4. admin 과목 생성
5. professor 담당 과목 조회
6. professor 자료 업로드
7. student 접근 과목 조회
8. student 챗봇 질문
9. 답변 출처 확인
10. ChatLog 저장 확인
```

---

## 17.3 권한 테스트

| 시나리오                           | 기대 결과    |
| ---------------------------------- | ------------ |
| 미로그인 사용자가 보호 API 호출    | 401          |
| student가 관리자 API 호출          | 403          |
| professor가 다른 교수 과목 수정    | 403          |
| student가 접근 권한 없는 과목 조회 | 403 또는 404 |
| admin이 전체 과목 조회             | 200          |

---

## 17.4 RAG 테스트

| 테스트             | 기대 결과            |
| ------------------ | -------------------- |
| 업로드된 자료 처리 | DocumentChunk 생성   |
| 질문 검색          | 관련 청크 top-k 반환 |
| 출처 포함 답변     | sources 배열 포함    |
| 자료 부족 질문     | 자료 부족 안내       |
| 과제 정답 요청     | 힌트 중심 답변       |

---

## 18. 개발 단계별 구현 범위

## 18.1 1단계: 프로젝트 기반 구축

```text id="qtbp4k"
- 프로젝트 구조
- 환경변수
- DB 연결
- 기본 엔티티
- README
```

---

## 18.2 2단계: 인증 / 권한 / 과목 / 업로드

```text id="gppx4w"
- JWT 로그인
- 역할 기반 권한 관리
- 관리자 과목 관리
- 교수자 담당 과목 조회
- 강의자료 업로드
- 학생 과목 목록 조회
```

---

## 18.3 3단계: 문서 처리 / RAG 검색

```text id="u33s69"
- 완료: TXT/PDF/DOCX/PPTX 텍스트 추출
- 완료: 청크 분할과 DocumentChunk 저장
- 완료: deterministic local hash 임베딩 생성
- 완료: JSON embedding과 local cosine 검색
- 완료: 과목 권한/범위 검색 API와 상태 API
- 완료: 교수자 처리 상태 및 검색 디버그 UI
```

---

## 18.4 4단계: 챗봇 / 출처 / SAFE / 로그

```text id="mtkpl3"
- 학생 챗봇 UI
- RAG 답변 생성
- 출처 표시
- SAFE 가드레일
- ChatLog 저장
- 대화 이력
```

---

## 18.5 5단계: 대시보드 / 통계 / MVP 마무리

```text id="4mhn0r"
- 관리자 대시보드
- 교수자 대시보드
- 통계 API
- 테스트
- README 업데이트
- 배포 준비
```

---

## 19. MVP 완료 기준

MVP는 다음 조건을 만족하면 완료로 본다.

```text id="hssm5l"
1. admin, professor, student 계정으로 로그인할 수 있다.
2. 역할별 페이지와 API 접근 제한이 동작한다.
3. admin은 과목을 생성, 수정, 활성화, 비활성화할 수 있다.
4. professor는 담당 과목에 강의자료를 업로드할 수 있다.
5. 업로드된 자료는 텍스트 추출, 청크 분할, 임베딩 처리가 가능하다.
6. student는 접근 가능한 과목에서 챗봇 질문을 할 수 있다.
7. 챗봇 답변은 강의자료 기반으로 생성된다.
8. 답변에는 출처가 표시된다.
9. 자료 부족 시 한계를 명시한다.
10. 과제/시험 정답 요청은 직접 답변하지 않고 학습 보조 방식으로 전환한다.
11. 질문과 답변 로그가 저장된다.
12. 교수자와 관리자는 권한 범위 내에서 로그를 확인할 수 있다.
13. 관리자 통계 화면에서 기본 사용 현황을 확인할 수 있다.
14. README만 보고 로컬 실행과 테스트가 가능하다.
```

---

## 20. 향후 고도화 고려사항

MVP 이후 다음 기능을 확장한다.

```text id="ucz4qs"
- I-Campus 연동
- 학교 SSO 연동
- 교수자 셀프 업로드 고도화
- 지식베이스 자동 버전 관리
- 소크라테스 모드 고도화
- 오개념 진단
- 관련 질문 추천
- 후속 질문 제안
- 교수 검수 기능
- FAQ 자동 생성
- 답변 만족도 평가
- RAG 검색 성능 최적화
- 교육 데이터셋 구축
- LLM 파인튜닝
- 전국 대학 배포 패키지화
```

---

## 21. 핵심 기술 원칙

```text id="dveq3x"
1. 과목별 데이터 격리를 반드시 보장한다.
2. 모든 AI 답변은 가능한 한 출처를 포함한다.
3. 출처 없는 답변은 확정적으로 말하지 않는다.
4. 학생의 과제/시험 부정행위를 돕지 않는다.
5. 권한 체크는 Backend에서 반드시 수행한다.
6. 업로드 파일과 비밀키는 Git에 포함하지 않는다.
7. RAG 모듈은 나중에 교체 가능하도록 인터페이스를 분리한다.
8. MVP에서는 단순하게 구현하되, 확장 가능한 구조를 유지한다.
```
