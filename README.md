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
- 소크라테스식 대화: 학생 답에 대한 피드백, 단계별 힌트, 한 번에 하나의 사고 질문
- 강의자료 근거가 부족할 때만 교수자가 등록한 신뢰 도메인에서 SearXNG 보충 검색
- 모든 음성·텍스트 turn은 기존 질문 로그(`ChatLog`)에 저장되어 교수자·관리자 화면에 노출
- 교수자·관리자 대시보드의 `취약 개념 현황`: 과목별 요약과 주제·개념·학생별 상세
  (`GET /api/stats/weak-concepts`, `GET /api/stats/weak-concepts/courses/{id}`; 교수자에게는
  학생 이메일이 마스킹됨)

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
Moss를 쓸 때도 같은 파일에 미러링되며, 교수자·관리자 통계는 이 파일을 읽습니다.

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

필수 도구는 [uv](https://docs.astral.sh/uv/), Python 3.12+, Node.js, Docker입니다.
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

환경 파일 복사, 의존성 설치, 데이터베이스 기동, 마이그레이션, Seed, 백엔드와
프론트엔드 실행까지 처리합니다. `Ctrl+C`로 둘 다 종료합니다.

- 웹: <http://localhost:3000>
- API 문서: <http://localhost:8000/docs>
- 앱 상태: <http://localhost:8000/api/health>
- Model Server 상태: <http://localhost:8000/api/health/model-server>

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

2. 주소를 `.env`에 넣습니다. LLM·Embedding 주소에만 `/v1`을 붙입니다. 아래는 VS Code 앱 경로
   프록시 형태의 예입니다.

   ```dotenv
   TEXT_LLM_BASE_URL=https://siriuscluster.skku.edu:10245/proxy/8001/v1
   VOICE_LLM_BASE_URL=https://siriuscluster.skku.edu:10245/proxy/8002/v1
   EMBEDDING_BASE_URL=https://siriuscluster.skku.edu:10245/proxy/8003/v1
   SPEECH_BASE_URL=https://siriuscluster.skku.edu:10245/proxy/8010
   TTS_BASE_URL=https://siriuscluster.skku.edu:10245/proxy/8012
   MODEL_SERVER_API_KEY=모델_서버와_동일한_키
   ```

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
