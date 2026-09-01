# SKKU Course Agent

성균관대학교 강의자료를 기반으로 답변하는 RAG 코스 에이전트입니다.

- 학생: 수강 과목 질문, 출처가 포함된 답변, 대화 이력 조회, COURSE AGENT 음성 대화
- 교수자: 담당 과목 자료 업로드·처리, 질문 로그와 통계 조회, 음성 조교 신뢰 사이트 관리
- 관리자: 사용자·과목·권한·전체 로그와 통계 관리

답변은 업로드된 강의자료를 우선 사용하고 출처를 표시합니다. 자료가 부족하면 이를
명시하며, 과제·시험의 정답 요청에는 정답 대신 개념과 힌트를 제공합니다.

화면은 성균관대학교 i-Campus(<https://canvas.skku.edu/>, Canvas LMS)의 전역 레일,
상단 바, 과목 메뉴 구조를 따릅니다. 이 MVP가 구현하지 않는 i-Campus 메뉴도 같은
자리에 비활성 상태로 표시해 실제 LMS와 동일한 배치를 유지합니다.

## 기술 구성

- Frontend: Next.js, TypeScript
- Backend: FastAPI, SQLAlchemy, Alembic
- Database: PostgreSQL, pgvector
- AI/RAG: 과목별 검색, local hash embedding, provider-neutral `LLMService`
- Default inference: 별도 `SKKU_AI_model_server`의 Qwen Text/Voice LLM + Qwen ASR/TTS
- Voice orchestration: FastAPI WebSocket + application CPU Silero VAD + interruptible cascade
- Trusted web: 교수자 allowlist + self-hosted SearXNG + application-side URL 재검증
- Weak-concept memory: Moss 선택 사용, 미설정 시 local JSON fallback
- Package management: npm workspace, uv workspace

애플리케이션 저장소는 Qwen weight, vLLM, qwen-asr, qwen-tts 또는 CUDA runtime을 로드하지
않습니다. GPU inference는 모두 별도 Model Server API가 담당합니다.

## COURSE AGENT

[kingo-voice-agent](https://github.com/lyh030725/kingo-voice-agent)를 과목 에이전트에
통합한 음성 조교입니다. 과목 메뉴의 `COURSE AGENT`에서 사용합니다.

- 텍스트 스트리밍 답변과 핸즈프리 음성 대화, barge-in, 동일 WebSocket 세션의 typed input
- 매 turn 전에 취약 개념과 강의자료를 사전 로딩하고 기존 course-scoped RAG를 그대로 사용
- 수식·단계 도식·좌표 그래프·강의 PDF 페이지 visualization 카드
- 응답과 분리된 External Brain이 완료된 대화를 진단해 취약 개념 저장·복습 상태 갱신
- 설명 모드와 소크라테스 모드
- 강의자료 근거가 부족할 때만 교수자가 등록한 신뢰 도메인에서 SearXNG 보충 검색
- 모든 음성·텍스트 turn은 기존 질문 로그(`ChatLog`)에 저장되어 교수자·관리자 화면에 노출

학생의 질문 창구는 과목 안의 COURSE AGENT 하나입니다. 별도의 "AI 질문" 메뉴와 탭은
없습니다. `대화 이력`에서 지난 대화를 열면 해당 과목의 COURSE AGENT가 그 대화를 다시
불러오고 같은 세션에 이어서 답변합니다.

### 모델 구성

기본 개발 구성은 self-hosted Model Server입니다.

```text
Typed COURSE AGENT
Frontend -> FastAPI -> RAG / Tools / SAFE -> LLMService
         -> Qwen/Qwen3.8-27B (:8001/v1)

Hands-free voice
Browser microphone -> FastAPI WebSocket -> Silero VAD (CPU)
 -> Qwen3-ASR (:8010)
 -> existing COURSE AGENT Brain / RAG / Tools / SAFE / Memory / Visualization
 -> Qwen/Qwen3.5-9B (:8002/v1, thinking disabled)
 -> Qwen3-TTS Sohee/Korean (:8010)
 -> PCM16 mono 24 kHz -> Browser speaker
```

`LLM_PROVIDER=local_qwen`, `VOICE_PROVIDER=local_cascade`에서는
`ANTHROPIC_API_KEY`와 `XAI_API_KEY`가 필요하지 않습니다. Anthropic과 xAI Grok은
회귀 비교를 위한 legacy provider로 남아 있습니다.

Moss 자격 증명이 없으면 취약 개념은 `uploads/voice/weak-concepts.json`에 로컬 저장됩니다.

## 프로젝트 구조

```text
apps/frontend       Next.js 웹 앱
apps/backend        FastAPI API와 데이터베이스 마이그레이션
packages/ai_rag     RAG 패키지
packages/shared     공통 TypeScript 타입과 스키마
infra/postgres      PostgreSQL 초기화
docs                제품·기술 문서
```

제품 요구사항과 상세 설계는 [PRD](docs/PRD.md)와
[기술 명세](docs/TEC_SPEC.md)를 참고하세요.

## 실행

필수 도구는 [uv](https://docs.astral.sh/uv/), Python 3.12+, Node.js입니다. 로컬 Docker 개발
환경에서는 PostgreSQL 기동을 위해 Docker도 사용합니다. 먼저 Model Server와 필요하면
SearXNG를 실행하고 `.env`에 endpoint를 설정합니다.

```dotenv
LLM_PROVIDER=local_qwen
TEXT_LLM_BASE_URL=http://MODEL_SERVER:8001/v1
TEXT_LLM_MODEL=Qwen/Qwen3.8-27B
VOICE_LLM_BASE_URL=http://MODEL_SERVER:8002/v1
VOICE_LLM_MODEL=Qwen/Qwen3.5-9B
SPEECH_BASE_URL=http://MODEL_SERVER:8010
MODEL_SERVER_API_KEY=
VOICE_PROVIDER=local_cascade
TTS_SPEAKER=Sohee
TTS_LANGUAGE=Korean
SEARXNG_URL=http://SEARXNG_SERVER:8080
```

### 로컬 Docker 개발

저장소 루트에서 실행합니다.

```bash
bash run.sh
```

환경 파일 복사, 의존성 설치, Docker PostgreSQL 기동, 마이그레이션, Seed, 백엔드와
프론트엔드 실행까지 처리합니다. `Ctrl+C`로 둘 다 종료합니다.

- 웹: <http://localhost:3000>
- API 문서: <http://localhost:8000/docs>
- 앱 상태: <http://localhost:8000/api/health>
- Model Server 상태: <http://localhost:8000/api/health/model-server>

### Backend.AI (학교 GPU 서버)

Backend.AI compute session 안에서는 Docker-in-Docker를 사용하지 않습니다. 별도
`SKKU_AI_model_server`가 같은 세션의 `127.0.0.1:8001`, `:8002`, `:8010`에서 이미 실행 중인
구성을 기준으로 하며, 애플리케이션은 CPU 프로세스로 FastAPI와 Next.js만 직접 실행합니다.
Model Server 포트는 브라우저에 공개할 필요가 없습니다.

Backend.AI용 구성 파일을 복사합니다.

```bash
cp .env.backendai.example .env
```

최소한 다음 값을 환경에 맞게 수정합니다.

```dotenv
# Backend.AI session에서 접근 가능한 PostgreSQL
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@DB_HOST:5432/course_agent
VECTOR_DB_URL=postgresql+psycopg://USER:PASSWORD@DB_HOST:5432/course_agent

# 같은 Backend.AI session에서 이미 실행 중인 Model Server
TEXT_LLM_BASE_URL=http://127.0.0.1:8001/v1
VOICE_LLM_BASE_URL=http://127.0.0.1:8002/v1
SPEECH_BASE_URL=http://127.0.0.1:8010

# Backend.AI App Proxy / Preopen Port URL
NEXT_PUBLIC_API_BASE_URL=https://BACKENDAI_BACKEND_APP_URL
BACKEND_CORS_ORIGINS=https://BACKENDAI_FRONTEND_APP_URL
```

현재 `VECTOR_SEARCH_MODE=local`은 embedding을 PostgreSQL JSON column에 저장하고 application
process에서 cosine ranking을 수행하므로 이 모드 자체는 pgvector 연산자를 요구하지 않습니다.
관계형 사용자/과목/자료/로그 저장을 위해 PostgreSQL은 반드시 필요합니다.

Backend.AI에서 preopen port/App Proxy 대상으로 다음 두 포트를 노출합니다.

```text
3000  Next.js frontend
8000  FastAPI REST/WebSocket backend
```

특히 COURSE AGENT 음성 WebSocket을 사용하려면 8000번 App Proxy가 WebSocket upgrade를
지원해야 합니다. `8001`, `8002`, `8010`은 같은 compute session 내부 loopback으로만
사용합니다.

실행은 Docker 없이 다음 한 명령으로 합니다.

```bash
bash run_backendai.sh
```

`.env`가 없으면 스크립트가 `.env.backendai.example`을 복사하고 안전한 JWT secret을 자동
생성한 뒤, DB 주소를 수정하도록 종료합니다. 설정이 완료된 실행에서는 다음을 순서대로
검증하고 하나라도 실패하면 즉시 중단합니다.

1. uv workspace/CPU-only Silero VAD 의존성
2. npm/Next.js 의존성
3. PostgreSQL `SELECT 1`
4. Text LLM, Voice LLM, Speech Server health
5. Alembic migration과 선택적 seed
6. FastAPI `0.0.0.0:8000` readiness
7. Next.js `0.0.0.0:3000` readiness
8. Application에서 다시 확인한 Model Server health

기본 frontend 모드는 `dev`입니다. 안정적인 build/start 형태를 사용하려면 `.env`에서
`BACKENDAI_FRONTEND_MODE=production`으로 변경합니다. seed가 필요하지 않은 환경은
`BACKENDAI_SEED=false`를 설정할 수 있습니다.

상태 확인과 종료:

```bash
bash healthcheck_backendai.sh
bash stop_backendai.sh
```

로그는 `logs/backendai/backend.log`, `logs/backendai/frontend.log`에 저장되고 PID 파일은
`.run/backendai/`에 저장됩니다. 이 스크립트들은 Application PID만 관리하며 별도
`SKKU_AI_model_server` 프로세스는 종료하지 않습니다.

### Model Server endpoint contract

Application이 사용하는 endpoint는 다음뿐입니다.

```text
GET  TEXT_LLM_BASE_URL/models
POST TEXT_LLM_BASE_URL/chat/completions
GET  VOICE_LLM_BASE_URL/models
POST VOICE_LLM_BASE_URL/chat/completions
GET  SPEECH_BASE_URL/health
POST SPEECH_BASE_URL/v1/audio/transcriptions
POST SPEECH_BASE_URL/v1/audio/speech
```

Model Server 인증을 사용하면 모든 요청에 `Authorization: Bearer ${MODEL_SERVER_API_KEY}`가
추가됩니다.

### 검증

전체 unit/regression/frontend 검증:

```bash
bash test.sh
```

실제 Model Server가 접근 가능한 환경의 optional smoke test:

```bash
uv run --all-packages --extra dev --extra voice python scripts/test_model_server_integration.py
```

한국어 독립 WAV를 함께 검사하려면 스크립트의 `--wav` 옵션을 사용합니다.

### Seed 계정

모든 계정의 초기 비밀번호는 `password123`입니다.

| 역할 | 이메일 | 시작 화면 |
| --- | --- | --- |
| 관리자 | `admin@skku.edu` | `/admin` |
| 교수자 | `professor@skku.edu` | `/professor` |
| 학생 | `student@skku.edu` | `/student` |

샘플 강의자료는 `docs/samples/ai-intro-sample.txt`에 있습니다.

## 주요 환경변수

| 변수 | 설명 |
| --- | --- |
| `DATABASE_URL` | PostgreSQL 연결 주소 |
| `JWT_SECRET` | JWT 서명 키. 비로컬 환경에서는 32자 이상의 고유 키 필요 |
| `BACKEND_CORS_ORIGINS` | 허용할 프론트엔드 Origin |
| `NEXT_PUBLIC_API_BASE_URL` | 브라우저에서 접근하는 FastAPI base URL |
| `UPLOAD_DIR` | 업로드 파일 저장 위치 |
| `MAX_UPLOAD_SIZE_BYTES` | 파일당 업로드 제한 |
| `LLM_PROVIDER` | `local_qwen`(기본), `mock`, `anthropic` |
| `TEXT_LLM_BASE_URL` / `TEXT_LLM_MODEL` | typed/External Brain Qwen endpoint와 model |
| `VOICE_LLM_BASE_URL` / `VOICE_LLM_MODEL` | realtime cascade의 Voice Qwen endpoint와 model |
| `SPEECH_BASE_URL` | Qwen ASR/TTS Speech Server |
| `MODEL_SERVER_API_KEY` | optional Model Server bearer key |
| `VOICE_PROVIDER` | `local_cascade`(기본) 또는 legacy `grok` |
| `TTS_SPEAKER` / `TTS_LANGUAGE` | 기본 `Sohee` / `Korean` |
| `VAD_THRESHOLD` / `SILENCE_MS` / `PREFIX_MS` | application-side Silero endpointing 설정 |
| `SEARXNG_URL` | self-hosted trusted-web search endpoint |
| `BACKENDAI_BACKEND_PORT` / `BACKENDAI_FRONTEND_PORT` | Backend.AI 내부 application ports |
| `BACKENDAI_FRONTEND_MODE` | `dev` 또는 `production` |
| `BACKENDAI_SEED` | Backend.AI 시작 시 seed 실행 여부 |
| `ANTHROPIC_API_KEY` / `CLAUDE_MODEL` | legacy Anthropic provider 전용 |
| `XAI_API_KEY` / `GROK_VOICE_MODEL` | legacy Grok voice provider 전용 |
| `MOSS_PROJECT_ID` / `MOSS_PROJECT_KEY` | 취약 개념 클라우드 메모리. 비우면 로컬 파일 사용 |

전체 기본값과 설명은 로컬 Docker 개발은 [.env.example](.env.example), Backend.AI는
[.env.backendai.example](.env.backendai.example)에 있습니다. 환경변수를 바꾼 뒤에는 API와
웹 프로세스를 다시 시작하세요.

## 문서 지원 범위

TXT, PDF, DOCX, PPTX의 텍스트를 처리합니다. 스캔 PDF OCR과 HWP는 지원하지 않습니다.
업로드 자료는 과목별로 격리되며, 학생·교수자·관리자의 역할과 과목 권한은 백엔드에서
검사합니다.
