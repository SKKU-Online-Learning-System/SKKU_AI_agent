# SKKU Course Agent — 핵심 구조

이 문서는 코드가 실제로 어떻게 동작하는지 설명합니다. 제품 요구사항은 [PRD](PRD.md),
상세 설계는 [기술 명세](TEC_SPEC.md)를 참고하세요.

## 1. 전체 흐름

```
학생 질문
   │
   ├─ SAFE 가드레일 (규칙 기반 분류)
   │     차단 → 안전 답변 반환, 로그 저장, 모델 호출 없음
   │     힌트 전환 → 정답 대신 개념·단계 힌트로 유도
   │
   ├─ COURSE AGENT 툴 루프 (Claude tool use)
   │     ├─ 취약 개념 회상  (Moss / 로컬 JSON)
   │     ├─ 강의자료 검색   (pgvector, course_id 한정)
   │     ├─ 신뢰 웹 검색    (근거 부족할 때만, 허용 도메인 한정)
   │     ├─ visualization  (수식·도식·그래프)
   │     └─ 취약 개념 저장/복습
   │
   └─ 답변 + 출처 + 시각자료 → ChatLog 저장
```

핵심 원칙 3가지:

| 원칙 | 구현 |
| --- | --- |
| **출처는 서버가 만든다** | 모델이 쓴 URL·파일명을 믿지 않음. 검색 결과에서 서버가 조립 |
| **검색은 과목에 갇힌다** | 모든 retrieval에 `course_id` 필터. 타 과목 자료 유출 불가 |
| **프로바이더 호출은 한 곳** | `LLMService`만 모델 SDK를 안다. `brain.py`는 SDK를 모름 |

## 2. 답변 생성 메커니즘

### 툴 루프 (`app/services/voice/brain.py` → `think()`)

```python
for _ in range(MAX_TOOL_ROUNDS):          # 최대 6라운드
    missing = [필수 툴 중 아직 안 부른 것]
    turn = await llm.stream_tool_turn(
        system=SYSTEM_PROMPT + 과목 컨텍스트 + 모드 프롬프트,
        messages=[대화 이력, ...이번 턴 tool_use/tool_result 블록],
        tools=anthropic_tools(),
        force_tools=missing,               # 비어있지 않으면 tool_choice=any
        on_token=on_token,                 # 텍스트 델타 스트리밍
    )
    if not turn.tool_calls:
        return 답변, 사용툴, 출처, 시각자료
    # tool_use 블록 → assistant 턴, tool_result 블록 → user 턴으로 누적
```

**강제 컨텍스트**: `recall_weak_concepts` + `search_course_materials` 두 개가 실행되기
전에는 `tool_choice: any`로 묶어 모델이 답변을 못 씁니다. 즉 근거 없이 먼저 말하는
경로가 구조적으로 막혀 있습니다.

**병렬 실행**: 한 턴에 여러 tool_use가 오면 `asyncio.gather`로 동시 실행.

**스트리밍**: 토큰이 생성되는 즉시 NDJSON으로 프론트에 흘려보냄 → 화면에 타이핑되듯 출력.

### 두 개의 스키마 형식

`TOOLS`는 OpenAI/realtime 형식으로 두고, `anthropic_tools()`가 Claude용 `input_schema`로
변환합니다. 실시간 음성(Grok)이 원본 형식을 그대로 먹기 때문에 하나의 정의로 두
프로바이더를 동시에 먹입니다.

### 답변 모드

| 모드 | 동작 |
| --- | --- |
| 설명 모드 | 개념 직접 설명 + 구체 예시 1개 + 이해 확인 질문 1개 |
| 소크라테스 모드 | 정답 먼저 말하지 않음. 초점 질문 1개 또는 단계 힌트 1개 |

## 3. Tool 6종

| Tool | 역할 | 저장 위치 |
| --- | --- | --- |
| `recall_weak_concepts` | 이 학생의 관련 취약 개념 회상 | Moss 인덱스 / 로컬 JSON |
| `search_course_materials` | 과목 강의자료 근거 검색 | pgvector (`document_chunks`) |
| `search_trusted_web` | 자료 근거 부족 시에만 외부 검색 | 감사 로그 JSONL |
| `save_weak_concept` | 혼란·오답·불완전 설명 시 취약 개념 저장 | Moss / 로컬 JSON |
| `review_weak_concept` | 복습 답변 채점 → 간격 반복 상태 갱신 | Moss / 로컬 JSON |
| `show_visualization` | 수식(LaTeX)·흐름도·좌표 그래프 카드 | 저장 안 함 (응답에 포함) |

### 세부 규칙

**`search_course_materials`** — 자체 PDF 인덱스가 아니라 기존 `RagService`를 호출합니다.
출처가 `파일명 p.페이지` 형태로 교수자 화면과 동일. 툴 디스패치는 요청 세션 밖에서
돌기 때문에 자체 `SessionLocal`을 엽니다.

**`search_trusted_web`** — 교수자가 등록한 도메인만 Claude 웹 검색에 넘기고, 응답을 받은
뒤 허용 목록으로 다시 한 번 걸러냅니다. 프로바이더 필터를 믿고 학생에게 링크를
노출하지 않습니다. 근거 URL이 하나도 없으면 에러를 반환하고, 모델은 자료가 부족하다고
말하게 됩니다.

**`show_visualization`** — 시스템 프롬프트가 수식·좌표를 대화문에 넣는 것을 금지합니다.
대신 이 툴로 카드를 만들고 "제가 보여드린 그림처럼"으로 참조합니다. 음성 답변에서
수식을 기호 단위로 읽는 사고를 막습니다. Pydantic으로 형태를 검증합니다 (formula는
latex 필수, flow는 라벨 2개 이상, plot은 점 2개 이상).

**취약 개념 안전망** — 학생이 "모르겠어요", "헷갈려요" 같은 표현을 썼는데 모델이
`save_weak_concept`를 안 불렀으면, 서버가 대신 저장합니다.

## 4. RAG 파이프라인

```
업로드
  ↓  MaterialProcessingService.process_material   ← 상태 락으로 중복 처리 차단
  ↓  DocumentParserService     TXT/PDF/DOCX/PPTX → 페이지별 텍스트 (제어문자 제거)
  ↓  ChunkingService           문단 우선 분할, 짧은 청크 병합, 오버랩
  ↓  EmbeddingService          local hash (기본) 또는 실제 임베딩 모델
  ↓  VectorStoreService        replace_material_chunks (재처리 시 기존 청크 교체)
검색
  ↓  RagService.retrieve(course_id, question, top_k)
```

`RetrievalOutcome.summary.reason`이 실패를 구분합니다:

| reason | 의미 | UI 배지 |
| --- | --- | --- |
| `None` (결과 있음) | 강의자료 근거 확보 | 강의자료 기반 |
| `NO_RELEVANT_CONTEXT` | 자료는 있으나 관련 없음 | 일반 개념 설명 |
| `NO_PROCESSED_MATERIAL` | 처리된 자료 자체가 없음 | 자료 미비 안내 |

`VECTOR_SEARCH_MODE`로 Python 코사인 유사도 ↔ pgvector를 전환합니다.

PDF·PPTX 추출은 NUL(0x00)을 포함한 C0 제어문자를 흘립니다. PostgreSQL `text` 컬럼이
NUL을 거부해 청크 INSERT 전체가 실패하므로, 모든 포맷이 합류하는 파서 지점에서
한 번에 제거합니다 (`app/services/document_parser.py`의 `sanitize_text`).

> `app/services/document_parser_service.py`는 같은 역할의 **구버전 중복 모듈**입니다.
> 파이프라인은 쓰지 않고 오래된 테스트만 import합니다. 파서를 고칠 때는
> `document_parser.py`를 고쳐야 합니다.

## 5. SAFE 가드레일

규칙 기반(정규식)입니다. MVP는 예측 가능하고 검토 가능한 동작이 필요하고, LLM
모더레이션으로 교체할 자리는 서비스 경계로 남겨뒀습니다.

| 분류 | 처리 |
| --- | --- |
| 프롬프트 인젝션 | **차단** — 내부 지시문 비공개 안내 |
| 개인정보 요청 | **차단** — 타인 정보 제공 불가 안내 |
| 안전하지 않은 요청 | **차단** — 교육 목적 외 거절 |
| 시험 정답 직접 요청 | **힌트 전환** — 개념·단계 안내 |
| 과제 전체 대행 | **힌트 전환** (개념·힌트 요청 허용 목록에 걸리면 정상 처리) |

차단 시 모델을 아예 호출하지 않고 안전 답변을 반환하되, 로그는 남깁니다.

## 6. 저장되는 것

### PostgreSQL

| 테이블 | 내용 |
| --- | --- |
| `users` | 계정, 역할(student/professor/admin), 해시 비밀번호 |
| `courses` | 과목, 학기, 담당 교수, 활성 여부 |
| `course_access` | 학생 ↔ 과목 수강 권한 |
| `course_materials` | 원본 파일명, 내부 UUID 파일명, 주차, 처리 상태·실패 사유 |
| `document_chunks` | 청크 텍스트, 페이지 번호, 임베딩 벡터, 임베딩 모델명 |
| `chat_sessions` | 대화 세션 (제목 자동 생성, 과목·사용자 귀속) |
| `chat_logs` | 감사 기록의 핵심 |

`chat_logs` 한 행에 들어가는 것:

```
question, answer
referenced_documents   출처 (material_id, 문서명, 페이지, 청크 인덱스, 점수)
retrieval_result       채널(voice/text), 모드, 사용한 tool 목록, 웹 출처, 결과 수
safety_result          차단 여부, 분류, 사유, 전환 유형
is_grounded            강의자료 근거 여부
answer_source_type     rag / general_llm / safety_response / no_material
model_name, response_time_ms
```

음성 turn도 텍스트 turn과 같은 테이블에 들어갑니다. 교수자·관리자 로그 화면이 음성
대화까지 그대로 볼 수 있습니다.

### 파일

```
uploads/{material_uuid}                        원본 강의자료 (내부 파일명은 UUID)
uploads/voice/weak-concepts.json               취약 개념 (Moss 미설정 시 로컬 폴백)
uploads/voice/trusted-sites/{course_id}.json   과목별 신뢰 도메인
uploads/voice/web-search.jsonl                 외부 검색 감사 로그 (질의·근거·사유·시각)
```

### 프로세스 메모리

`(사용자, 과목)`당 `VoiceContext` 1개 — 대화 이력 최근 12개 메시지. 재시작하면
사라지지만, `대화 이력`에서 세션을 열면 `ChatLog`에서 복원됩니다.

## 7. 역할별 기능과 기대 효과

### 학생

| 기능 | 위치 |
| --- | --- |
| COURSE AGENT 텍스트 질문 (스트리밍 답변) | 과목 › COURSE AGENT |
| 핸즈프리 음성 대화 (서버 VAD, 말 끊기 지원) | 같은 화면 마이크 |
| 설명 / 소크라테스 모드 전환 | 같은 화면 |
| 수식·도식·그래프 카드 | 답변에 자동 삽입 |
| 강의자료 열람 (주차별) | 과목 › 강의콘텐츠 |
| 대화 이력 → 그 대화 이어서 질문 | 대시보드 › 대화 이력 |

기대 효과

- 질문 창구가 과목 안 한 곳으로 통일 — 어디서 물어야 하는지 고민할 필요 없음
- 답변마다 파일명·페이지가 붙어 원문 확인 경로가 항상 열려 있음
- 소크라테스 모드가 정답을 먼저 주지 않아 사고 과정을 유지
- 약한 개념이 자동 기록되고 간격 복습으로 되돌아옴
- 음성으로 이동 중에도 학습 가능

### 교수자

| 기능 | 위치 |
| --- | --- |
| 강의자료 업로드 + 즉시 색인 | 과목 › COURSE AGENT 설정 |
| 신뢰 사이트 등록·삭제 (과목별) | 같은 화면 |
| 처리 실패 확인 및 재처리 | 강의자료 관리 |
| 질문 로그 열람·필터 (근거 여부, SAFE 분류, 기간, 키워드) | 질문 로그 |
| RAG 검색 디버그 (실제 검색 결과·점수 확인) | 과목 › RAG 디버그 |
| 과목 통계 (질문 수 추이, 최근 질문, 키워드) | 대시보드 |

기대 효과

- 자료를 올리는 것만으로 조교가 생김 — 프롬프트 작성 불필요
- 학생들이 어디서 막히는지 로그로 관측 → 다음 강의 보완 지점 확보
- 외부 검색 범위를 직접 통제 → 근거 없는 답변·부적절한 출처 차단
- RAG 디버그로 "왜 이렇게 답했는지"를 검색 결과 수준에서 추적

### 관리자

| 기능 | 위치 |
| --- | --- |
| 과목 생성·수정·활성화/비활성화 | 관리자 › 과목 |
| 사용자 목록·역할 조회 | 관리자 › 사용자 |
| 과목별 수강 권한 확인 | 과목 설정 |
| 전체 자료 현황 | 관리자 › 자료 |
| 전체 질문 로그 (모든 과목) | 관리자 › 질문 로그 |
| 서비스 통계 (과목·사용자·질문 수, 일자별 추이) | 대시보드 |

기대 효과

- 과목 비활성화 한 번으로 접근 차단
- 전체 로그·통계로 운영 리스크(차단 사례, 근거 없는 답변 비율) 조기 감지
- 역할·과목 권한이 전부 백엔드에서 강제 — 프론트 우회 불가

## 8. 모델 구성

| 용도 | 모델 | 키 없으면 |
| --- | --- | --- |
| 텍스트 답변 · tool 호출 | Claude (`CLAUDE_MODEL`) | 모의 응답으로 동작 |
| 신뢰 웹 검색 | Claude web search | 비활성 (자료 근거만 사용) |
| 임베딩 | local hash (기본) | 항상 동작 |
| 실시간 음성 | xAI Grok realtime | 마이크 버튼만 비활성 |
| 취약 개념 메모리 | Moss | 로컬 JSON 폴백 |

`USE_MOCK_LLM=true`(기본)에서 모의 LLM이 tool 호출 턴까지 흉내냅니다. 그래서 API 키
하나 없이 전체 플로우가 돌고, 테스트도 end-to-end로 검증됩니다.

실시간 음성만 xAI인 이유는 Claude에 realtime voice API가 없기 때문입니다. 이 한
곳(`grok_live.py`)이 `LLMService` 경계의 유일한 예외입니다.
