# 멀티모달 강의자료 검색

검색 모델은 **Qwen/Qwen3-VL-Embedding-2B (BF16)**, 이미지 판독은 기존
**Qwen/Qwen3.5-9B**다. 음성 발화 모델을 교체하지 않았고, 같은 9B 서버의 이미지 입력을 활성화했다.
모델은 별도 Model Server에서만 실행한다.

## 실제 경로

1. TXT는 기존 청크 분할 후 텍스트 임베딩한다.
2. PDF는 페이지 전체를 렌더링한다. PPTX/DOCX는 격리된 LibreOffice 프로필로 PDF 변환 후 렌더링한다.
   도형·화살표·표·그래프·스캔 내용이 페이지 이미지에 남는다. DOCX 페이지 번호는 이 렌더링 기준이다.
3. 업로드 응답(201/pending) 후 서버 BackgroundTasks가 자체 DB 세션으로 처리를 시작한다.
   기존 원자적 상태 claim을 사용하므로 같은 자료를 중복 처리하지 않는다.
4. 페이지마다 9B가 질문에 독립적인 텍스트·수식·표·축·단위·수치·화살표 관계를 미리 읽는다.
   `page_evidence`에 저장하며 불명확한 값은 추정하지 않도록 지시한다.
5. 이미지 임베딩, 원문 텍스트, JPEG, 판독 결과, 자료 ID·페이지 번호를 같은 트랜잭션으로 저장한다.
   모든 페이지가 성공해야 completed가 된다. 재처리 실패 시 이전 청크와 해석은 보존한다.
6. 매 대화 턴 최근 대화와 현재 질문으로 과목 범위의 동일 모델 벡터를 cosine 검색한다.
   검색된 최대 2페이지의 **저장된 판독 결과**와 원문·출처를 즉시 반환한다.
7. 원본 재판독은 별도 요청인
   `POST /api/courses/{course_id}/materials/{material_id}/pages/{page_number}/inspect`
   (`{"question": "확인할 세부 정보"}`)로 제공한다. 과목·자료·완료 상태·페이지를 검증한다.
   대화 모델에는 새 판독 도구를 추가하지 않는다. 시험에서 모델이 이미 있는 근거도
   반복 판독했으므로, 이 선택적 도구를 음성 경로에 넣는 방식은 채택하지 않았다.

기존 `page_evidence IS NULL` 이미지 청크는 호환을 위해 질문별 판독을 사용하므로 재색인이 필요하다.
저장된 판독은 해당 청크의 원본 이미지와 동일한 처리 결과다. 자료 재처리 시 청크 전체가 교체된다.
해석은 모델 출력이므로 원본 확인 기능과 누락 정보의 선택적 재확인을 유지한다.

교수자 자료 목록과 음성 설정 화면은 pending/processing 상태에서 5초 간격으로 갱신한다.
실패는 기존 processing-status 및 재처리 기능으로 확인한다. 업로드 처리 작업은 현재 앱 프로세스에서
실행된다. 프로세스 강제 종료에 대한 자동 재시도/분산 큐는 없으며, 그 운영 요건이 생기면 durable
worker로 이전해야 한다. 중단된 processing 자료를 재시작할 때는 실행 중인 작업이 없는지 확인한 뒤
관리자가 상태를 복구해야 한다. 일반 처리 예외는 failed로 기록된다.

`GET /api/courses/{course_id}/materials/{material_id}/pages/{page_number}/image`는
과목 권한 검사 후 원본 렌더링을 반환한다. 검색 API의 `pageImageUrl` 및 교수자 검색 화면에서
판독 내용을 원본과 비교할 수 있다. 이미지는 검색 대상 전체를 읽을 때 로드하지 않고,
선정된 페이지 또는 원본 조회에서만 가져온다.

## 설치 및 실행

애플리케이션 CPU 의존성은 uv.lock에 고정했다. PPTX/DOCX에는 시스템 렌더러와 한글 폰트가 필요하다.

```bash
sudo apt-get install --no-install-recommends libreoffice-impress libreoffice-writer fonts-noto-cjk
UV_PROJECT_ENVIRONMENT=.venv-app uv sync --locked --all-packages --extra dev --extra voice
.venv-app/bin/alembic -c apps/backend/alembic.ini upgrade head
PYTHONPATH=apps/backend .venv-app/bin/python scripts/reindex_materials.py --all
```

`DATABASE_URL`은 실제 사용 DB로 지정해야 한다. `run.sh`의 Docker 없는 개발 모드는
`sqlite:////home/work/workspace/SKKU_AI_agent/course-agent.sqlite`를 사용한다.
`--course-id` 또는 `--material-id`로 재색인 범위를 제한할 수 있다.
실패한 문서는 failed 상태와 오류를 남기며, 기존 청크 삭제는 전체 페이지 판독·임베딩 성공 후에 수행한다.

Model Server의 `scripts/start_all.sh`는 embedding도 시작한다. 독립 시작은
`scripts/start_embedding.sh`. 기본 GPU 5, 포트 8003, 메모리 비율 0.27이다.
9B 서버는 `VOICE_LANGUAGE_MODEL_ONLY=false`가 필요하며, 기본 GPU 4/포트 8002를 유지한다.
새로운 별도 비전 생성 모델은 필요 없다.

주요 앱 설정은 `.env.example` 참조:

- `EMBEDDING_PROVIDER=qwen`, `EMBEDDING_DIMENSION=2048`
- `VISION_LLM_BASE_URL=http://localhost:8002/v1`, `VISION_LLM_MODEL=Qwen/Qwen3.5-9B`
- `RAG_SCORE_THRESHOLD=0.22` (페이지 이미지), `RAG_TEXT_SCORE_THRESHOLD=0.4` (TXT)
- `RAG_VISUAL_MAX_PAGES=2`, `DOCUMENT_MAX_PAGES=300`, `DOCUMENT_RENDER_MAX_SIDE=1600`

두 cutoff는 점수 분포가 다른 텍스트/이미지에 각각 적용한다. 확률이나 정확도 보장이 아니므로
강의 자료·질문 분포가 바뀌면 평가로 보정해야 한다. 현재 검색은 course-scoped exact scan이다.
대규모 ANN 인덱스나 reranker는 추가하지 않았다.

## 임베딩 입력의 필수 조건

[공식 Qwen 모델](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B)은 마지막 토큰 표현을 사용한다.
이 체크포인트의 tokenizer는 `<|endoftext|>`를 덧붙인다. vLLM chat embedding 요청에는
**`add_generation_prompt=true`와 `add_special_tokens=true`가 모두 필요**하다.
후자를 생략하면 벡터 길이가 정상이어도 다른 벡터 공간이 만들어진다.
공식 Transformers와 vLLM을 비교한 cosine은 수정 전 0.397–0.496, 수정 후 0.99965–0.99976이었다.

Model Server `scripts/check_embedding_parity.py`는 토큰 배열과 벡터 일치를 검사한다.
모델 교체나 serving 변경 시 실행하고 벡터를 재색인한다.

## 검증

```bash
bash test.sh
PYTHONPATH=apps/backend .venv-app/bin/python scripts/eval_multimodal_retrieval.py
```

두 번째 명령은 실제 모델 서버와 LibreOffice를 사용한다. 격리된 SQLite에서 이미지로만 구성된
PDF, PPTX, DOCX를 처리하고, 학습률 0.10의 손실 값 1.2를 검색·판독하며 다른 과목 자료를 배제한다.
일반 단위 테스트에는 모델 다운로드나 실제 서버가 필요 없다.

[실제 강의 자료 판독 결과](evaluations/multimodal-corpus-20260911.json),
[형식별 실측](evaluations/multimodal-formats-20260911.json),
[페이지 검색 순위](evaluations/multimodal-ranking-20260911.json).

현재 Transformer PDF 3개, 82페이지의 재색인을 완료했다. 실제 그림과 대조한 항목:

| 질문 | 검색 1순위 | 확인한 근거 |
|---|---|---|
| 인과 마스크 3번 행 | Part1 PDF 14페이지 | 0–3열은 ✓, 4–7열은 × |
| MHA/GQA/MQA 연결 | Part3 PDF 20페이지 | Q 8개, KV 각각 8/4/1개, 연결 비율 1:1/2:1/8:1 |
| 위치 인코딩 그래프 축 | Part1 PDF 23페이지 | 가로 Depth, 세로 Position |
| 내적 점수가 학습에 미치는 영향 | Part1 PDF 8페이지 | sharp softmax와 very small gradients |
| 서울 날씨 | 결과 없음 | 강의 근거로 잘못 반환하지 않음 |

도표 3종의 이미지 판독은 원본과 일치했다. 내적 질문에서는 핵심 근거를 읽었지만,
판독 모델이 서두에 “직접 설명이 없다”는 불필요한 유보 문장을 붙였다. 판독 모델의 오류 가능성은
남아 있으므로 원본 비교를 지원한다. 이 평가는 모든 도표의 무오류 판독을 보장하지 않는다.
초기 실측에서 실제 강의 한 페이지의 검색+판독은 약 5–11초였고,
스캔/Office 숫자 사례는 수초였다. 이는 발화/TTS 지연을 포함하지 않는다.
이 수치는 이전 질문별 이미지 판독 경로다. 사전 판독 적용 후 수치는 아래 새 평가를 참고한다.

최종 검증: Python 352개, 프런트엔드 78개 테스트 통과. Ruff, TypeScript, ESLint,
프런트엔드 production build 통과. Text/Voice/Embedding/ASR/TTS health 모두 200,
이미지 입력 활성화 후에도 Voice Qwen3.5-9B의 텍스트 응답을 확인했다.
최근 인과 마스크 대화를 붙인 “응”, “모르겠어”, “0번부터 3번까지요”도 모두
Part1 PDF 14페이지를 1순위로 검색했다 (cosine 0.354 / 0.367 / 0.374).

사전 판독 적용 후 측정과 한계는 [새 검증 보고서](evaluations/voice-precomputed-report-20260911.md)를 참조한다.
