# SKKU Course Agent

성균관대학교 강의자료를 기반으로 답변하는 RAG 코스 에이전트입니다.

- 학생: 수강 과목 질문, 출처가 포함된 답변, 대화 이력 조회, COURSE AGENT 음성 대화
- 교수자: 담당 과목 자료 업로드·처리, 주차별 핵심 키워드 집계 조회, 음성 조교 신뢰 사이트 관리
- 관리자: 사용자·과목·권한 관리, 사용량 및 키워드 집계 조회

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
- 소크라테스식 대화: 학생 답에 대한 피드백, 단계별 힌트, 한 번에 하나의 사고 질문
- 강의자료 근거가 부족할 때만 교수자가 등록한 신뢰 도메인에서 SearXNG 보충 검색
- 음성·텍스트 대화는 `ChatLog`에 저장되고 해당 대화 계정의 이력에만 표시
- 교수자 메뉴 `핵심 키워드`: 담당 과목의 주차, 승인 용어, 질문 건수만 표시

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
 -> existing COURSE AGENT Brain / RAG / Tools / SAFE / Memory
 -> Qwen/Qwen3.5-9B (:8002/v1, thinking disabled, compact validated finish_turn)
 -> TTS starts while a separate 9B visual worker renders optional visuals asynchronously
 -> Qwen3-TTS Sohee/Korean (:8012, streaming)
 -> PCM16 mono 24 kHz -> Browser speaker
```

`LLM_PROVIDER=local_qwen`, `VOICE_PROVIDER=local_cascade`에서는
`ANTHROPIC_API_KEY`와 `XAI_API_KEY`가 필요하지 않습니다. Anthropic과 xAI Grok은
회귀 비교를 위한 legacy provider로 남아 있습니다.

Moss 자격 증명이 없으면 취약 개념은 `uploads/voice/weak-concepts.json`에 로컬 저장됩니다.
Moss를 쓸 때도 같은 파일에 미러링됩니다. 취약 개념은 학생 본인의 복습에만 사용합니다.

### 대화 보호 및 로그인

- `핵심 키워드`는 같은 과목·주차에서 서로 다른 학생 5명 이상이 질문한 승인 용어만 공개합니다.
  한 질문에 같은 용어가 여러 번 있어도 1건입니다. 학습 화면에서 열어 둔 교안의 주차를
  우선 사용하고, 없으면 답변이 인용한 해당 과목 교안을 기준으로 합니다. 주차가 확인되지
  않거나 SAFE 분류가 일반 질문이 아닌 대화는 집계에서 제외합니다.
- 기본 용어 대신 과목별 승인 용어를 쓰려면 `COURSE_KEYWORD_TERMS={"과목_ID":["학습률","경사하강법"]}`
  처럼 설정합니다. `KEYWORD_MINIMUM_STUDENTS`는 5 이상으로 높일 수 있습니다.
- 학생 질문·답변, 대화 제목과 첨부 기록은 교수자와 관리자에게 제공하지 않습니다.
  이는 앱의 접근 제한입니다. DB·파일과 백업 자체의 암호화, 운영자 접근 권한, 모델 서버 및
  선택형 외부 메모리(Moss)의 데이터 처리 정책은 실제 학생 데이터 투입 전에 별도 점검합니다.
- 로그아웃은 브라우저 쿠키 제거와 함께 서버에서 해당 JWT를 폐기합니다. 새 버전으로
  시작할 때 Alembic을 최신 상태로 적용하고 다시 로그인하세요. 비밀번호 시도 제한은
  현재 프로세스 단위입니다. 여러 워커로 배포할 때는 공용 제한을 적용해야 합니다.
- `APP_ENV`가 `local`이 아니면 데모 계정 seed 명령을 실행할 수 없습니다.
  이미 존재하는 데모 계정은 자동 삭제하지 않으므로 운영 DB에 가져오지 마세요.

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

필수 도구는 [uv](https://docs.astral.sh/uv/), Python 3.12+, Node.js입니다.
기본 실행은 Docker의 PostgreSQL 16을 사용합니다. 이미 접속할 수 있는 PostgreSQL이 있으면 Docker는 필요 없습니다.
먼저 Model Server와 필요하면 SearXNG를 실행하고 `.env`에 endpoint를 설정합니다.

```dotenv
LLM_PROVIDER=local_qwen
TEXT_LLM_BASE_URL=http://localhost:8001/v1
TEXT_LLM_MODEL=Qwen/Qwen3.8-27B
VOICE_LLM_BASE_URL=http://localhost:8002/v1
VOICE_LLM_MODEL=Qwen/Qwen3.5-9B
SPEECH_BASE_URL=http://localhost:8010
TTS_BASE_URL=http://localhost:8012
EMBEDDING_BASE_URL=http://localhost:8003/v1
MODEL_SERVER_API_KEY=서버와_동일한_키
VOICE_PROVIDER=local_cascade
TTS_SPEAKER=ryan
TTS_LANGUAGE=Korean
SEARXNG_URL=http://SEARXNG_SERVER:8080
```

localhost 값은 모델 서버가 같은 머신에 있을 때의 기본값입니다. 모델 서버가 Backend.AI 세션에
있으면 아래 "모델 서버가 Backend.AI에 있을 때"대로 공개 앱 주소를 넣습니다.

그 뒤 저장소 루트에서 실행합니다.

```bash
bash run.sh
```

환경 파일 복사, 의존성 설치, 데이터베이스 기동, 마이그레이션, 빈 DB의 데모 데이터 생성, 백엔드와
프론트엔드 실행까지 처리합니다. `Ctrl+C`로 둘 다 종료합니다.

- DB는 노트북의 `127.0.0.1:5432`에서만 수신합니다. 데이터는 `postgres_data` 볼륨에 남습니다.
- 8000번 포트를 다른 앱이 쓰고 있으면 `BACKEND_PORT=18000 bash run.sh`로 실행할 수 있습니다.
- Docker가 꺼져 있어도 SQLite로 자동 전환하지 않습니다. 기존 `course-agent.sqlite`는 수정하거나
  PostgreSQL에 자동으로 가져오지 않습니다. 기존 Docker DB에 기록이 있으면 아래처럼 먼저 백업하세요.

- 웹: <http://localhost:3000>
- API 문서: <http://localhost:8000/docs>
- 앱 상태: <http://localhost:8000/api/health>
- Model Server 상태: <http://localhost:8000/api/health/model-server>

### 이미 설치된 PostgreSQL 사용

`.env`에 `APP_ENV=local`과 앱용 개발 DB의 `DATABASE_URL`(`postgresql+psycopg://`)을 설정합니다.
전용 DB를 먼저 만들고, 초기화하거나 버전을 올릴 때만 대상 DB를 확인한 뒤 다음 명령을 실행합니다.

```bash
UV_PROJECT_ENVIRONMENT=.venv-app uv run --locked --all-packages --extra dev --extra voice \
  alembic -c apps/backend/alembic.ini upgrade head
bash run.sh --external-db
```

`--external-db`는 Docker를 실행하지 않고 DB 스키마 버전만 확인합니다. 데모 계정을 생성하지
않습니다. PostgreSQL은 사용자·과목·자료·대화와 임베딩을 저장합니다. 현재 검색은
`VECTOR_SEARCH_MODE=local`에서 JSON 임베딩의 코사인 유사도를 계산하므로 외부 DB에
pgvector 확장을 반드시 설치할 필요는 없습니다.

### 로컬 백업과 복구

파일과 DB가 같은 시점의 상태를 갖도록 앱을 종료하고 DB 컨테이너만 실행한 상태에서 백업합니다.
`UPLOAD_DIR`를 바꿨다면 스크립트에 실제 경로를 인자로 전달합니다.

```bash
bash scripts/backup_local_postgres.sh
```

`backups/`에 `db.dump`와 `uploads.tar.gz`가 생성됩니다(업로드 폴더가 없으면 덤프만 생성).
별도 경로를 쓰려면 `BACKUP_ROOT`를 지정하세요. 외부 경로의 취약 개념 메모리 파일과 환경
설정은 별도로 보관합니다. 덤프와 파일에는 개인 대화·첨부가 포함될 수 있으므로 접근을
제한하고 암호화된 별도 저장소에도 복사하세요. 로컬 백업은 서버나 디스크 장애에 대비한
별도 보관본을 대체하지 않습니다.

기존 DB에 덮어쓰지 않고, 사용하지 않는 새 DB 이름으로 복구를 먼저 확인합니다.

```bash
docker compose exec -T db createdb -U course_agent course_agent_restore
docker compose exec -T db pg_restore -U course_agent -d course_agent_restore \
  --exit-on-error --single-transaction --no-owner < /path/to/backup/db.dump
```

업로드 압축도 별도 폴더에 풀어 DB의 자료 경로와 대조합니다. 운영 복구에서 파일 경로가 바뀌면
원래 경로에 배치하거나 경로를 이전해야 합니다. 이전 버전의 덤프를 복구한 경우, 복구 DB를
가리키도록 설정한 후 그 DB에만 최신 마이그레이션을 적용합니다. `docker compose down -v`는
원본 DB 볼륨을 삭제하므로 일상 종료에 사용하지 않습니다.

### PostgreSQL 회귀 테스트

별도로 만든 테스트 DB의 URL을 `TEST_POSTGRES_URL`로 설정하고 실행합니다. 테스트는
임시 스키마를 만들어 Alembic으로 마이그레이션하고 삭제하므로, 해당 계정에 스키마 생성
권한이 필요합니다. 운영 DB나 실제 학생 데이터가 있는 DB를 지정하지 마세요.

```bash
UV_PROJECT_ENVIRONMENT=.venv-app uv run --locked --all-packages --extra dev --extra voice \
  pytest apps/backend/tests/test_stage4_chat_api.py apps/backend/tests/test_question_keywords_api.py
```

### 모델 서버가 Backend.AI에 있을 때

앱은 로컬(개발은 `run.sh`, 배포는 Docker)에서 돌고, 모델 서버만 Backend.AI 세션에서 돕니다.
앱은 Backend.AI에 올리지 않으므로 세션의 `8000`, `8004`는 쓰지 않습니다.

1. 모델 서버 다섯 서비스(`8001` Text LLM, `8002` Voice LLM, `8003` Embedding, `8010` Speech ASR,
   `8012` 스트리밍 TTS)의 공개 주소를 확보합니다. 주소는 두 형태 중 하나입니다.

- **포트별 Backend.AI 앱** — 콘솔에서 8001·8002·8003·8010·8012를 각각 **Open app to public**으로
  열면 포트마다 `https://siriuscluster.skku.edu:1xxxx` 주소가 나옵니다.
- **VS Code(code-server) 앱의 경로 프록시** — `https://siriuscluster.skku.edu:10245/proxy/<포트>`.
  다섯 서비스 모두 호출·인증이 되는 것을 확인했지만, 스트리밍 응답의 **첫 청크가 생성이 끝나는
  시점까지 지연**됩니다(9B 150토큰: 직접 0.14초 → 프록시 3.9초, 이후 청크는 정상 간격). 첫 토큰·첫
  음성까지의 시간이 그만큼 늘어나므로 음성 지연이 중요하면 포트별 앱 주소를 씁니다.

2. 주소를 `.env`에 넣습니다. VS Code 앱 경로 프록시라면 `MODEL_SERVER_PROXY` 한 줄이면 됩니다.
   다섯 `*_BASE_URL`은 preopen port로 여기서 파생되므로 세션이 바뀌어도 이 줄의 포트만 고칩니다.

   ```dotenv
   MODEL_SERVER_PROXY=https://siriuscluster.skku.edu:10241/proxy
   MODEL_SERVER_API_KEY=모델_서버와_동일한_키
   ```

   포트별 앱은 주소가 서로 다르므로 `MODEL_SERVER_PROXY`를 비우고 다섯 `*_BASE_URL`에 각각 넣습니다.
   LLM·Embedding 주소에만 `/v1`을 붙입니다.

3. `bash run.sh`로 앱을 띄우고 <http://localhost:8000/api/health/model-server>에서 다섯 endpoint가
   모두 `ok`인지 확인합니다.

모든 주소는 같은 `MODEL_SERVER_API_KEY`로 보호되며, 세션이 살아 있는 동안만 유지됩니다. 세션을
다시 만들면 주소가 바뀌므로 `.env`도 갱신해야 합니다. 모델 서버 쪽 설정은
`SKKU_AI_model_server/README.md`의 "Backend.AI Preopen Ports"를 참고합니다.

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
| `UPLOAD_DIR` | 업로드 파일 저장 위치 |
| `MAX_UPLOAD_SIZE_BYTES` | 파일당 업로드 제한 |
| `LLM_PROVIDER` | `local_qwen`(기본), `mock`, `anthropic` |
| `TEXT_LLM_BASE_URL` / `TEXT_LLM_MODEL` | typed/External Brain Qwen endpoint와 model |
| `VOICE_LLM_BASE_URL` / `VOICE_LLM_MODEL` | realtime cascade의 Voice Qwen endpoint와 model |
| `SPEECH_BASE_URL` / `TTS_BASE_URL` | Qwen ASR endpoint(`8010`) / 스트리밍 TTS endpoint(`8012`) |
| `EMBEDDING_BASE_URL` / `EMBEDDING_MODEL` | 멀티모달 임베딩 endpoint(`8003`)와 model |
| `MODEL_SERVER_API_KEY` | optional Model Server bearer key |
| `VOICE_PROVIDER` | `local_cascade`(기본) 또는 legacy `grok` |
| `TTS_SPEAKER` / `TTS_LANGUAGE` | 기본 `Sohee` / `Korean` |
| `VAD_THRESHOLD` / `SILENCE_MS` / `PREFIX_MS` | application-side Silero endpointing 설정 |
| `SEARXNG_URL` | self-hosted trusted-web search endpoint |
| `ANTHROPIC_API_KEY` / `CLAUDE_MODEL` | legacy Anthropic provider 전용 |
| `XAI_API_KEY` / `GROK_VOICE_MODEL` | legacy Grok voice provider 전용 |
| `MOSS_PROJECT_ID` / `MOSS_PROJECT_KEY` | 취약 개념 클라우드 메모리. 비우면 로컬 파일 사용 |

전체 기본값과 설명은 [.env.example](.env.example)에 있습니다. 환경변수를 바꾼 뒤에는
API와 웹 개발 서버를 다시 시작하세요.

## 문서 지원 범위

TXT, PDF, DOCX, PPTX의 텍스트를 처리합니다. 스캔 PDF OCR과 HWP는 지원하지 않습니다.
업로드 자료는 과목별로 격리되며, 학생·교수자·관리자의 역할과 과목 권한은 백엔드에서
검사합니다.
