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
- AI/RAG: 과목별 검색, local hash embedding, Claude 또는 mock LLM
- Voice: 텍스트·tool 추론은 Claude, 실시간 음성만 xAI Grok, Moss 취약 개념 메모리 (선택)
- Package management: npm workspace, uv workspace

## COURSE AGENT

[kingo-voice-agent](https://github.com/lyh030725/kingo-voice-agent)를 과목 에이전트에
통합한 음성 조교입니다. 과목 메뉴의 `COURSE AGENT`에서 사용합니다.

- 텍스트 스트리밍 답변과 핸즈프리 음성 대화(서버 VAD, barge-in)
- 6개 function tool: 취약 개념 회상·저장·복습, 강의자료 검색, 신뢰 웹 검색, visualization
- 수식·단계 도식·좌표 그래프 visualization 카드
- 설명 모드와 소크라테스 모드
- 강의자료 근거는 기존 과목 RAG(pgvector)를 그대로 사용하며 파일명·페이지를 출처로 표시
- 강의자료 근거가 부족할 때만 교수자가 등록한 신뢰 도메인에서 보충 검색
- 모든 음성·텍스트 turn은 기존 질문 로그(`ChatLog`)에 저장되어 교수자·관리자 화면에 노출

학생의 질문 창구는 과목 안의 COURSE AGENT 하나입니다. 별도의 "AI 질문" 메뉴와 탭은
없습니다. `대화 이력`에서 지난 대화를 열면 해당 과목의 COURSE AGENT가 그 대화를 다시
불러오고 같은 세션에 이어서 답변합니다.

### 모델 구성

텍스트 답변, tool 호출, 신뢰 웹 검색은 모두 이 프로젝트의 `LLMService`(Claude 또는
`USE_MOCK_LLM=true`의 모의 응답)를 사용합니다. 그래서 기본 설정 그대로, API 키 없이도
COURSE AGENT가 동작합니다. 핸즈프리 음성만 xAI Grok realtime을 사용합니다. Claude에
실시간 음성 API가 없기 때문이며, `XAI_API_KEY`가 비어 있으면 마이크 버튼만 비활성화되고
텍스트 대화는 그대로 동작합니다.

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

필수 도구는 [uv](https://docs.astral.sh/uv/), Python 3.12+, Node.js, Docker입니다.
저장소 루트에서 다음 하나만 실행하면 됩니다.

```bash
bash run.sh
```

환경 파일 복사, 의존성 설치, 데이터베이스 기동, 마이그레이션, Seed, 백엔드와
프론트엔드 실행까지 모두 처리합니다. `Ctrl+C`로 둘 다 종료합니다.

기본 설정은 로컬 PostgreSQL과 mock LLM을 사용하므로 Claude API 키 없이 실행할 수
있습니다. 실제 Claude를 사용하려면 `.env`에서 `USE_MOCK_LLM=false`로 변경하고
`ANTHROPIC_API_KEY`를 설정하세요. 비밀키와 로컬 환경 파일은 커밋하지 않습니다.

- 웹: <http://localhost:3000>
- API 문서: <http://localhost:8000/docs>
- 상태 확인: <http://localhost:8000/api/health>

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
| `USE_MOCK_LLM` | `true`이면 API 키 없이 mock 답변 사용 |
| `ANTHROPIC_API_KEY` | Claude API 키 |
| `CLAUDE_MODEL` | 답변 생성 모델 |
| `XAI_API_KEY` | COURSE AGENT의 핸즈프리 음성용 xAI 키. 비우면 마이크 버튼만 비활성 |
| `GROK_VOICE_MODEL` / `GROK_VOICE` | 실시간 음성 모델과 보이스 |
| `MOSS_PROJECT_ID` / `MOSS_PROJECT_KEY` | 취약 개념 클라우드 메모리. 비우면 로컬 파일 사용 |

전체 기본값과 설명은 [.env.example](.env.example)에 있습니다. 환경변수를 바꾼 뒤에는
API와 웹 개발 서버를 다시 시작하세요.

## 문서 지원 범위

TXT, PDF, DOCX, PPTX의 텍스트를 처리합니다. 스캔 PDF OCR과 HWP는 지원하지 않습니다.
업로드 자료는 과목별로 격리되며, 학생·교수자·관리자의 역할과 과목 권한은 백엔드에서
검사합니다.
