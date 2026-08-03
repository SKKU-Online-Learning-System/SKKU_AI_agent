# Codex용 3단계 세부 개발 프롬프트

## 3단계 목표

3단계의 목표는 **교수자가 업로드한 강의자료를 AI가 검색 가능한 지식베이스로 변환하는 것**이다.

2단계에서 구현된 기능:

- 사용자 인증
- 역할 기반 권한 관리
- 과목 관리
- 교수자 강의자료 업로드
- CourseMaterial 메타데이터 저장
- processing_status = pending

3단계에서 구현할 기능:

- 문서 처리 파이프라인
- 텍스트 추출
- 청크 분할
- 임베딩 생성
- 벡터 저장
- 과목별 검색 API
- 자료 처리 상태 관리
- 교수자 자료 처리 UI
- RAG 검색 테스트

---

## 사용 순서

```text id="step3-order"
3-0. 현재 2단계 구현 상태 점검
3-1. 문서 처리 파이프라인 구조 설계
3-2. 텍스트 추출 기능 구현
3-3. 청크 분할 및 DocumentChunk 저장
3-4. 임베딩 생성 서비스 구현
3-5. 벡터 저장소 인터페이스 구현
3-6. 과목별 문서 검색 API 구현
3-7. 교수자 자료 처리 상태 UI 구현
3-8. RAG 검색 품질 테스트 및 디버그 도구 구현
3-9. 3단계 통합 테스트 및 README/문서 업데이트
```

---

# 3-0. 현재 2단계 구현 상태 점검 프롬프트

```text id="codex-step3-0"
너는 이 프로젝트의 시니어 풀스택 개발자야.

지금부터 “코스 에이전트 MVP”의 3단계 기능을 구현하려고 한다.

3단계의 목표는 교수자가 업로드한 강의자료를 문서 처리, 청크 분할, 임베딩 생성, 벡터 저장 과정을 거쳐 검색 가능한 RAG 지식베이스로 만드는 것이다.

먼저 현재 레포지토리의 2단계 구현 상태를 점검해줘.

확인해야 할 것:
1. User, Course, CourseAccess 또는 CourseEnrollment, CourseMaterial 모델이 존재하는지 확인해줘.
2. CourseMaterial에 다음 필드가 있는지 확인해줘.
   - id
   - course_id
   - uploaded_by
   - original_file_name
   - file_name
   - file_type
   - file_size
   - storage_path
   - processing_status
   - processing_error
   - created_at
   - updated_at
3. 교수자 자료 업로드 API가 구현되어 있는지 확인해줘.
4. 업로드된 파일이 실제 파일 시스템 또는 스토리지에 저장되는지 확인해줘.
5. 파일 저장 경로를 어떻게 관리하는지 확인해줘.
6. 현재 DB/ORM/마이그레이션 방식을 확인해줘.
7. 현재 백엔드 구조가 서비스 레이어를 분리하고 있는지 확인해줘.
8. 권한 체크 함수가 재사용 가능한지 확인해줘.
9. 3단계 구현에 필요한 파일 목록을 정리해줘.

아직 코드를 수정하지 말고 분석만 해줘.

출력 형식:
- 현재 구현 상태 요약
- 3단계 구현 가능 여부
- 부족한 모델/필드
- 수정이 필요한 DB 스키마
- 사용할 수 있는 기존 권한 함수
- 사용할 수 있는 기존 업로드 함수
- 3단계 구현 계획
- 예상 수정 파일 목록
```

---

# 3-1. 문서 처리 파이프라인 구조 설계 프롬프트

```text id="codex-step3-1"
이제 3단계의 문서 처리 파이프라인 구조를 먼저 구현해줘.

목표:
- CourseMaterial 상태가 pending인 자료를 처리할 수 있는 구조를 만든다.
- 문서 처리 흐름을 서비스 레이어로 분리한다.
- 텍스트 추출, 청크 분할, 임베딩 생성, 벡터 저장 단계를 나중에 각각 교체할 수 있게 인터페이스를 분리한다.

처리 흐름:
1. CourseMaterial 조회
2. 권한 확인
3. processing_status를 processing으로 변경
4. 파일 존재 여부 확인
5. 텍스트 추출
6. 청크 분할
7. 임베딩 생성
8. DocumentChunk 저장
9. processing_status를 completed로 변경
10. 실패 시 processing_status를 failed로 변경하고 processing_error 저장

이번 프롬프트에서는 전체 구조와 상태 전환을 우선 구현해줘.
텍스트 추출, 청크 분할, 임베딩, 벡터 저장은 아직 mock 또는 placeholder로 두어도 된다.

Backend API:

1. POST /courses/{course_id}/materials/{material_id}/process
   권한:
   - professor: 본인 담당 과목만 가능
   - admin: 모든 과목 가능

   처리:
   - material_id가 course_id에 속하는지 확인
   - 권한 확인
   - processing_status가 pending 또는 failed인 경우에만 처리 가능
   - 이미 processing이면 409 또는 적절한 에러 반환
   - 처리 시작 후 상태를 processing으로 변경
   - 처리 성공 시 completed
   - 처리 실패 시 failed

2. POST /courses/{course_id}/materials/{material_id}/reprocess
   권한:
   - professor: 본인 담당 과목만 가능
   - admin: 모든 과목 가능

   처리:
   - 기존 DocumentChunk가 있으면 삭제하거나 비활성화
   - processing_status를 processing으로 변경
   - 다시 처리 수행

3. GET /courses/{course_id}/materials/{material_id}/processing-status
   권한:
   - professor: 본인 담당 과목
   - admin: 모든 과목

   응답:
   {
     "material_id": "...",
     "processing_status": "pending",
     "processing_error": null,
     "chunk_count": 0,
     "updated_at": "..."
   }

구현해야 할 서비스 구조 예시:
- MaterialProcessingService
- DocumentParserService
- ChunkingService
- EmbeddingService
- VectorStoreService 또는 DocumentChunkRepository

주의:
- 지금은 비동기 큐를 반드시 도입하지 않아도 된다.
- MVP에서는 API 요청 안에서 동기 처리해도 된다.
- 다만 나중에 background worker로 옮기기 쉽도록 processMaterial(materialId) 같은 서비스 함수로 분리해줘.
- 처리 도중 실패해도 material 상태가 processing에 영원히 머물면 안 된다.
- 오류 메시지는 processing_error에 저장해줘.
- 같은 자료를 동시에 두 번 처리하지 않도록 최소한의 방어 로직을 넣어줘.

수용 기준:
- pending 자료에 대해 process API를 호출하면 상태가 processing을 거쳐 completed 또는 failed가 되어야 한다.
- 실패 시 failed 상태와 processing_error가 저장되어야 한다.
- 권한 없는 사용자는 처리 API를 호출할 수 없어야 한다.
- professor는 본인 담당 과목 자료만 처리할 수 있어야 한다.
- admin은 모든 자료를 처리할 수 있어야 한다.
- reprocess API를 호출하면 기존 처리 결과를 초기화할 수 있어야 한다.
- 텍스트 추출/청크/임베딩은 아직 mock이어도 파이프라인 구조가 유지되어야 한다.

작업 후 출력:
- 구현한 API 목록
- 구현한 서비스 목록
- 처리 상태 전환 방식
- 실패 처리 방식
- 동시 처리 방어 방식
- 테스트 방법
```

---

# 3-2. 텍스트 추출 기능 구현 프롬프트

```text id="codex-step3-2"
이제 문서 텍스트 추출 기능을 구현해줘.

목표:
- CourseMaterial에 저장된 원본 파일에서 텍스트를 추출한다.
- 최소 TXT와 PDF 파일을 처리한다.
- DOCX, PPTX는 가능하면 구현하고, 어렵다면 명확한 TODO와 graceful failure를 남긴다.
- 추출 결과는 이후 청크 분할 단계에서 사용할 수 있는 표준 형식으로 반환한다.

지원 우선순위:
1. TXT: 필수
2. PDF: 필수
3. DOCX: 가능하면 구현
4. PPTX: 가능하면 구현
5. HWP: MVP에서는 지원하지 않고 명확한 에러 처리

구현할 서비스:
- DocumentParserService

권장 인터페이스:
parseMaterial(material: CourseMaterial): ParsedDocument

ParsedDocument 예시:
{
  "material_id": "...",
  "course_id": "...",
  "title": "lecture1.pdf",
  "pages": [
    {
      "page_number": 1,
      "text": "..."
    },
    {
      "page_number": 2,
      "text": "..."
    }
  ],
  "full_text": "..."
}

파일별 처리:
1. TXT
   - UTF-8로 읽기
   - 인코딩 오류에 대비
   - 전체 내용을 page_number = null 또는 1로 처리

2. PDF
   - 현재 프로젝트 언어에 맞는 안정적인 라이브러리 사용
   - 페이지별 텍스트 추출이 가능하면 page_number를 유지
   - 페이지별 추출이 어렵다면 full_text만이라도 추출

3. DOCX
   - 가능하면 paragraph 텍스트 추출
   - 페이지 번호는 없어도 됨

4. PPTX
   - 가능하면 슬라이드별 텍스트 추출
   - slide_number를 page_number처럼 사용

5. 지원하지 않는 확장자
   - DOCUMENT_UNSUPPORTED_TYPE 에러 발생
   - processing_status = failed
   - processing_error에 사유 저장

주의:
- 빈 텍스트가 추출되면 성공으로 처리하지 말고 failed 처리해줘.
- 스캔 PDF처럼 텍스트가 없는 PDF는 “텍스트를 추출할 수 없습니다”라는 에러를 남겨줘.
- OCR은 MVP 범위가 아니므로 구현하지 않는다.
- 추출된 텍스트를 로그에 그대로 길게 출력하지 마.
- 한글 텍스트가 깨지지 않도록 주의해줘.
- 파일 경로는 CourseMaterial.storage_path를 기준으로 읽어줘.
- 파일이 존재하지 않으면 MATERIAL_FILE_NOT_FOUND 에러 처리해줘.

수용 기준:
- TXT 파일에서 텍스트를 추출할 수 있어야 한다.
- PDF 파일에서 텍스트를 추출할 수 있어야 한다.
- 텍스트가 없는 파일은 failed 처리되어야 한다.
- 지원하지 않는 파일 형식은 명확한 에러를 반환해야 한다.
- ParsedDocument의 구조가 청크 분할 단계에서 사용 가능해야 한다.
- 기존 process API에 실제 텍스트 추출 단계가 연결되어야 한다.

작업 후 출력:
- 지원하는 파일 형식
- 사용한 파서 라이브러리
- ParsedDocument 구조
- 실패 케이스 처리 방식
- 테스트 방법
```

---

# 3-3. 청크 분할 및 DocumentChunk 저장 프롬프트

```text id="codex-step3-3"
이제 텍스트 청크 분할과 DocumentChunk 저장 기능을 구현해줘.

목표:
- 추출된 문서 텍스트를 RAG 검색에 적합한 청크 단위로 분할한다.
- 각 청크를 DB에 DocumentChunk로 저장한다.
- 청크에는 과목, 자료, 페이지, 순서 정보가 포함되어야 한다.

DB 모델 추가 또는 확인:

DocumentChunk
- id
- course_id
- material_id
- chunk_index
- chunk_text
- page_number
- section_title
- token_count 또는 char_count
- embedding
- embedding_model
- created_at
- updated_at

주의:
- embedding 필드는 3-4 또는 3-5에서 채워질 수 있으므로 nullable이어도 된다.
- pgvector를 사용한다면 embedding vector 타입을 고려해줘.
- 아직 pgvector를 도입하지 않았다면 embedding_json 또는 별도 테이블로 임시 저장해도 된다.
- 단, 나중에 VectorStoreService로 교체하기 쉽게 해줘.

청크 분할 정책:
- 기본 chunk_size: 1000자 또는 800~1200 tokens에 해당하는 크기
- 기본 chunk_overlap: 150자 또는 100~200 tokens에 해당하는 크기
- 문단 단위 분할을 우선한다.
- 문단이 너무 길면 글자 수 기준으로 자른다.
- 너무 짧은 청크는 앞뒤 청크와 합치거나 제외한다.
- 한글/영문 혼합 텍스트를 고려한다.

구현할 서비스:
- ChunkingService

권장 인터페이스:
createChunks(parsedDocument: ParsedDocument): DocumentChunkInput[]

DocumentChunkInput 예시:
{
  "course_id": "...",
  "material_id": "...",
  "chunk_index": 0,
  "chunk_text": "...",
  "page_number": 3,
  "section_title": null,
  "char_count": 950
}

기능 요구사항:
1. ParsedDocument.pages를 입력받아 페이지 정보를 유지하며 청크를 만든다.
2. 각 청크의 chunk_index는 material 기준으로 0부터 순차 증가한다.
3. chunk_text 앞뒤 공백을 정리한다.
4. 빈 청크는 저장하지 않는다.
5. processing 전에 기존 material_id의 DocumentChunk가 있으면 삭제하거나 재처리 정책에 따라 정리한다.
6. 청크 저장 후 CourseMaterial의 chunk_count를 계산할 수 있으면 좋다.

수용 기준:
- TXT/PDF에서 추출된 텍스트가 여러 개의 청크로 분할되어야 한다.
- DocumentChunk가 DB에 저장되어야 한다.
- course_id, material_id, chunk_index, page_number가 올바르게 저장되어야 한다.
- reprocess 시 기존 청크가 중복 저장되지 않아야 한다.
- 너무 짧거나 빈 청크가 저장되지 않아야 한다.
- process API 완료 후 chunk_count를 확인할 수 있어야 한다.

작업 후 출력:
- 추가/수정한 DB 모델
- 청크 분할 기준
- overlap 처리 방식
- 저장되는 메타데이터
- reprocess 시 기존 청크 처리 방식
- 테스트 방법
```

---

# 3-4. 임베딩 생성 서비스 구현 프롬프트

```text id="codex-step3-4"
이제 DocumentChunk에 대한 임베딩 생성 기능을 구현해줘.

목표:
- 각 DocumentChunk의 chunk_text를 임베딩 벡터로 변환한다.
- 외부 API Key 없이 동작하는 deterministic local hash embedding을 사용한다.

구현할 서비스:
- EmbeddingService

권장 인터페이스:
embedText(text: string): number[]
embedTexts(texts: string[]): number[][]

주의:
- 임베딩 코드는 한 곳에 모아줘.
- 같은 텍스트에 대해 같은 로컬 벡터를 반환해야 한다.
- batch embedding을 지원하면 좋다.
- 너무 긴 chunk_text를 거부하도록 최대 입력 길이를 검증해줘.
- 임베딩 생성 실패 시 해당 material의 processing_status가 failed가 되어야 한다.
- 성능과 문제 추적을 위해 처리할 청크 수와 텍스트 길이를 로그로 요약해줘. 단, 본문 전체를 로그에 남기지 마.

DB 저장:
- DocumentChunk.embedding에 벡터 저장
- DocumentChunk.embedding_model에 모델명 저장
- embedding 생성 시각 필드가 있으면 저장

Local hash embedding 요구사항:
- VectorStoreService에서 동일하게 처리 가능해야 한다.
- 128차원 local hash vector
- 같은 텍스트 입력 → 같은 벡터 출력
- cosine similarity 테스트가 가능해야 함

수용 기준:
- DocumentChunk의 chunk_text로 임베딩을 생성할 수 있어야 한다.
- 외부 API 없이 임베딩이 생성되어야 한다.
- 임베딩 결과가 DocumentChunk에 저장되어야 한다.
- process API에서 청크 저장 후 임베딩 생성까지 연결되어야 한다.
- 임베딩 실패 시 material 상태가 failed가 되어야 한다.

작업 후 출력:
- 임베딩 서비스 구조
- local hash embedding 사용 방식
- DB 저장 방식
- 테스트 방법
```

---

# 3-5. 벡터 저장소 인터페이스 구현 프롬프트

```text id="codex-step3-5"
이제 벡터 저장소 인터페이스를 구현해줘.

목표:
- DocumentChunk의 embedding을 기반으로 유사도 검색을 할 수 있게 한다.
- 우선 현재 프로젝트에 가장 적합한 방식으로 구현하되, 나중에 pgvector 또는 전용 Vector DB로 교체하기 쉽게 인터페이스를 분리한다.
- 검색은 반드시 course_id로 제한되어야 한다.

구현할 서비스:
- VectorStoreService

권장 인터페이스:
upsertChunks(chunks: DocumentChunk[]): void
deleteChunksByMaterial(materialId: string): void
searchSimilarChunks(courseId: string, queryEmbedding: number[], topK: number): SearchResult[]

SearchResult 예시:
{
  "chunk_id": "...",
  "course_id": "...",
  "material_id": "...",
  "chunk_text": "...",
  "page_number": 3,
  "score": 0.87,
  "document_name": "lecture1.pdf"
}

구현 방식 우선순위:
1. pgvector가 이미 사용 가능하면 pgvector 기반 cosine similarity 검색 구현
2. pgvector 설정이 아직 어렵다면 DB에 저장된 embedding을 읽어 애플리케이션 레벨에서 cosine similarity 계산
3. 단, 2번 방식은 MVP 개발용임을 코드와 문서에 명확히 표시

pgvector 사용 시:
- embedding 컬럼 타입을 vector로 설정
- cosine distance 또는 inner product 검색 사용
- course_id 필터를 반드시 먼저 적용
- 필요한 index 생성 검토

애플리케이션 레벨 검색 시:
- course_id로 DocumentChunk 필터링
- embedding이 null이 아닌 청크만 가져오기
- cosine similarity 계산
- score 기준 정렬
- topK 반환

주의:
- 다른 과목의 청크가 절대 검색 결과에 섞이면 안 된다.
- embedding이 없는 청크는 검색에서 제외한다.
- topK 기본값은 5로 둔다.
- topK 최대값 제한을 둔다. 예: max 20
- 검색 결과에는 material 원본 파일명도 포함해줘.
- score가 너무 낮은 결과는 threshold로 제외할 수 있게 해줘.
- threshold는 환경변수 또는 설정값으로 분리하면 좋다.

환경변수 예시:
- VECTOR_SEARCH_MODE=pgvector 또는 local
- RAG_TOP_K=5
- RAG_SCORE_THRESHOLD=0.3

수용 기준:
- 특정 course_id 안에서만 유사 청크를 검색할 수 있어야 한다.
- queryEmbedding과 유사한 청크 topK가 반환되어야 한다.
- 검색 결과에 문서명, 페이지 번호, 청크 내용, score가 포함되어야 한다.
- embedding이 없는 청크는 검색되지 않아야 한다.
- 다른 과목 자료가 검색 결과에 섞이지 않아야 한다.
- pgvector를 쓰지 않더라도 local search로 MVP 테스트가 가능해야 한다.

작업 후 출력:
- VectorStoreService 구조
- 선택한 검색 방식
- cosine similarity 계산 방식
- course_id 필터링 방식
- 환경변수 목록
- 테스트 방법
```

---

# 3-6. 과목별 문서 검색 API 구현 프롬프트

```text id="codex-step3-6"
이제 과목별 문서 검색 API를 구현해줘.

목표:
- 사용자가 질문을 입력하면 해당 과목의 DocumentChunk 중 관련도 높은 청크를 반환한다.
- 이 API는 4단계 챗봇 답변 생성의 기반이 된다.
- 검색 API는 반드시 권한 검사와 과목 범위 제한을 수행해야 한다.

Backend API:

1. POST /rag/search

Request:
{
  "course_id": "course-id",
  "question": "경사하강법이 뭐야?",
  "top_k": 5
}

권한:
- student: 본인이 접근 가능한 활성 과목만 검색 가능
- professor: 본인 담당 과목만 검색 가능
- admin: 모든 과목 검색 가능

처리 흐름:
1. JWT 인증 확인
2. course_id 접근 권한 확인
3. question 유효성 검사
4. top_k 기본값 및 최대값 처리
5. question 임베딩 생성
6. VectorStoreService.searchSimilarChunks 호출
7. 검색 결과 반환

Response 예시:
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
      "chunk_text": "경사하강법은 손실 함수를 줄이기 위해...",
      "score": 0.87
    }
  ]
}

에러 처리:
- 인증 없음: 401
- 권한 없음: 403
- 과목 없음: 404
- question 비어 있음: 400 또는 422
- 처리 완료된 자료가 없음: 200 with empty results 또는 명확한 message
- embedding 실패: 500 또는 RAG_SEARCH_FAILED
- 검색 실패: RAG_SEARCH_FAILED

추가 API:

2. GET /courses/{course_id}/rag/status

권한:
- 해당 과목 접근 권한 필요

응답:
{
  "course_id": "...",
  "material_count": 3,
  "completed_material_count": 2,
  "failed_material_count": 1,
  "chunk_count": 120,
  "embedded_chunk_count": 120,
  "is_search_ready": true
}

주의:
- 검색 API는 답변을 생성하지 않는다.
- LLM Chat Completion 호출은 4단계에서 구현한다.
- 지금은 관련 청크를 반환하는 것까지만 한다.
- 검색 결과의 chunk_text가 너무 길면 적절히 제한하거나 그대로 반환하되 UI에서 접을 수 있도록 한다.
- 개발 디버깅을 위해 score를 반환한다.
- 운영 모드에서는 score 노출 여부를 나중에 설정할 수 있게 해도 좋다.

수용 기준:
- 학생은 본인이 접근 가능한 과목에 대해서만 검색할 수 있어야 한다.
- 교수자는 본인 담당 과목에 대해서만 검색할 수 있어야 한다.
- 관리자는 모든 과목을 검색할 수 있어야 한다.
- 질문을 입력하면 관련 청크 topK가 반환되어야 한다.
- 자료가 아직 처리되지 않은 과목은 is_search_ready=false여야 한다.
- 다른 과목 청크가 결과에 포함되면 안 된다.

작업 후 출력:
- 구현한 API 목록
- 검색 요청/응답 구조
- 권한 체크 방식
- 검색 준비 상태 판단 기준
- 테스트 방법
```

---

# 3-7. 교수자 자료 처리 상태 UI 구현 프롬프트

```text id="codex-step3-7"
이제 교수자 화면에 자료 처리 상태 UI를 구현해줘.

목표:
- 교수자는 업로드한 자료가 RAG 지식베이스로 처리되었는지 확인할 수 있다.
- 교수자는 pending 또는 failed 상태의 자료를 처리하거나 재처리할 수 있다.
- 처리 상태, 실패 원인, 청크 수를 화면에서 확인할 수 있다.

대상 화면:
- /professor/courses/[courseId]/materials
또는 현재 프로젝트의 교수자 자료 관리 화면

표시해야 할 정보:
- 원본 파일명
- 파일 형식
- 파일 크기
- 업로드 일시
- processing_status
- processing_error
- chunk_count
- 처리 시작 버튼
- 재처리 버튼
- 삭제 버튼

processing_status 표시:
- pending: 처리 대기
- processing: 처리 중
- completed: 처리 완료
- failed: 처리 실패

버튼 정책:
1. pending
   - “처리 시작” 버튼 표시

2. processing
   - 버튼 비활성화
   - “처리 중” 표시
   - 가능하면 새로고침 또는 상태 재조회 버튼 제공

3. completed
   - “재처리” 버튼 표시
   - chunk_count 표시

4. failed
   - 실패 원인 표시
   - “재처리” 버튼 표시

Frontend 동작:
1. 자료 목록 조회
2. 처리 시작 버튼 클릭
3. POST /courses/{course_id}/materials/{material_id}/process 호출
4. 성공 후 자료 목록 또는 status 재조회
5. 실패 시 오류 메시지 표시

추가 기능:
- GET /courses/{course_id}/rag/status 결과를 활용하여 과목 전체 검색 준비 상태 표시
- 예: “이 과목은 검색 준비 완료”, “처리된 자료가 없습니다”

주의:
- 처리 중인 자료에 대해 중복 클릭이 되지 않도록 해줘.
- API 호출 중 loading 상태를 표시해줘.
- 처리 실패 사유는 교수자가 이해할 수 있는 메시지로 표시해줘.
- 교수자가 다른 교수의 과목 자료 처리 화면에 접근하면 차단되어야 한다.
- 관리자 화면이 이미 있다면 관리자도 자료 처리 상태를 볼 수 있게 재사용 가능한 컴포넌트로 만드는 것이 좋다.

수용 기준:
- 교수자가 자료 처리 상태를 볼 수 있어야 한다.
- pending 자료를 처리 시작할 수 있어야 한다.
- completed 자료의 chunk_count를 볼 수 있어야 한다.
- failed 자료의 processing_error를 볼 수 있어야 한다.
- failed 자료를 재처리할 수 있어야 한다.
- 처리 중 버튼 중복 클릭이 방지되어야 한다.
- 권한 없는 사용자는 자료 처리 버튼을 사용할 수 없어야 한다.

작업 후 출력:
- 수정한 화면 목록
- 추가한 컴포넌트 목록
- 처리 상태 표시 방식
- 버튼 활성화 정책
- 테스트 방법
```

---

# 3-8. RAG 검색 품질 테스트 및 디버그 도구 구현 프롬프트

```text id="codex-step3-8"
이제 RAG 검색 품질을 확인할 수 있는 테스트와 디버그 도구를 구현해줘.

목표:
- 문서가 제대로 청크화되고 검색되는지 개발자가 쉽게 확인할 수 있게 한다.
- 4단계 챗봇 구현 전에 검색 품질을 검증한다.
- local hash embedding 환경에서 동작해야 한다.

구현할 기능:

1. 개발용 검색 테스트 페이지 또는 관리자/교수자 디버그 UI
   경로 예시:
   - /professor/courses/[courseId]/rag-debug
   또는
   - /admin/rag-debug

   기능:
   - 과목 선택
   - 질문 입력
   - top_k 선택
   - 검색 실행
   - 검색 결과 표시

2. 검색 결과 표시 항목
   - score
   - document_name
   - page_number
   - chunk_index
   - chunk_text preview
   - material_id
   - chunk_id

3. Backend debug 옵션
   - 검색 API 응답에 debug=true일 때 추가 정보 포함 가능
   - 예:
     - embedding_model
     - search_mode
     - score_threshold
     - total_candidate_chunks

4. CLI 또는 Script 테스트
   가능하면 seed 자료를 처리하고 검색하는 개발용 스크립트를 만들어줘.

   예시 흐름:
   - sample material 생성
   - process material 실행
   - “경사하강법이 뭐야?” 검색
   - top 결과 출력

5. 테스트용 샘플 자료
   가능하면 uploads 또는 fixtures에 샘플 TXT 파일을 추가해줘.
   예시 과목:
   - 인공지능개론

   샘플 내용:
   - 머신러닝
   - 지도학습
   - 경사하강법
   - 과적합
   - 평가 지표

주의:
- 디버그 페이지는 운영 환경에서 숨기거나 admin/professor만 접근 가능하게 해줘.
- 학생에게는 score나 raw chunk debug 정보를 보여주지 않아도 된다.
- 샘플 파일이 실제 업로드 흐름을 우회하지 않도록 주의해줘.
- 테스트 데이터는 seed 또는 fixtures로 분리해줘.
- 긴 chunk_text는 preview로 접어서 보여줘.

수용 기준:
- 개발자가 특정 과목에서 질문을 입력하고 검색 결과를 확인할 수 있어야 한다.
- 검색 결과에 score와 출처 정보가 표시되어야 한다.
- local hash embedding 환경에서도 검색 테스트가 가능해야 한다.
- 검색 결과가 course_id로 제한되는지 확인할 수 있어야 한다.
- 4단계 챗봇 구현 전에 RAG 검색이 정상 동작하는지 검증 가능해야 한다.

작업 후 출력:
- 구현한 디버그 UI 또는 스크립트
- 검색 결과 표시 항목
- 테스트 샘플 자료 위치
- local hash embedding 테스트 방법
- 실제 embedding 테스트 방법
```

---

# 3-9. 3단계 통합 테스트 및 README/문서 업데이트 프롬프트

```text id="codex-step3-9"
이제 3단계 기능을 통합 테스트하고 README와 docs 문서를 업데이트해줘.

목표:
- 업로드된 자료가 텍스트 추출, 청크 분할, 임베딩 생성, 벡터 저장, 검색까지 정상 동작하는지 확인한다.
- README와 기술 문서에 3단계 구현 내용을 반영한다.
- 4단계 챗봇 답변 생성으로 넘어갈 수 있는 상태로 마무리한다.

통합 테스트 시나리오:

1. Seed 데이터 준비
   - admin 계정
   - professor 계정
   - student 계정
   - 예시 과목
   - 학생 과목 접근 관계

2. 교수자 자료 업로드
   - professor 로그인
   - 담당 과목 접속
   - TXT 또는 PDF 자료 업로드
   - CourseMaterial processing_status = pending 확인

3. 문서 처리
   - 처리 시작 버튼 클릭 또는 process API 호출
   - processing_status = processing 확인
   - 텍스트 추출 수행
   - DocumentChunk 생성 확인
   - embedding 생성 확인
   - processing_status = completed 확인

4. 검색 준비 상태 확인
   - GET /courses/{course_id}/rag/status 호출
   - chunk_count > 0
   - embedded_chunk_count > 0
   - is_search_ready = true

5. 검색 API 테스트
   - POST /rag/search 호출
   - 관련 청크 topK 반환 확인
   - document_name, page_number, chunk_text, score 포함 확인

6. 권한 테스트
   - student는 접근 가능한 과목만 검색 가능
   - student는 접근 권한 없는 과목 검색 불가
   - professor는 담당 과목만 검색 가능
   - admin은 모든 과목 검색 가능

7. 실패 테스트
   - 지원하지 않는 파일 형식 처리
   - 텍스트가 없는 파일 처리
   - 존재하지 않는 파일 처리
   - 임베딩 실패 처리
   - 처리 중 중복 process 요청 처리

README 업데이트 내용:
1. 3단계 구현 기능 추가
   - 문서 처리
   - 텍스트 추출
   - 청크 분할
   - 임베딩 생성
   - 벡터 검색
   - 검색 API
   - 자료 처리 상태 UI

2. local hash embedding 설정 확인
   - VECTOR_SEARCH_MODE
   - RAG_TOP_K
   - RAG_SCORE_THRESHOLD

3. RAG 처리 흐름 문서화

4. 지원 파일 형식 정리
   - TXT
   - PDF
   - DOCX/PPTX 지원 여부
   - HWP 미지원 또는 추후 검토

5. 주요 API 추가
   - POST /courses/{course_id}/materials/{material_id}/process
   - POST /courses/{course_id}/materials/{material_id}/reprocess
   - GET /courses/{course_id}/materials/{material_id}/processing-status
   - GET /courses/{course_id}/rag/status
   - POST /rag/search

6. 테스트 방법 추가
   - local hash embedding으로 테스트
   - 권한 테스트
   - 검색 품질 테스트

docs/TECH_SPEC.md 업데이트:
- 실제 구현된 3단계 구조 반영
- 선택한 벡터 검색 방식 반영
- DocumentChunk 스키마 실제 구현 기준으로 수정
- RAG 검색 API 실제 endpoint 기준으로 수정
- 아직 구현되지 않은 챗봇 답변 생성은 4단계 Roadmap에 유지

주의:
- README에 실제 구현되지 않은 기능을 완료처럼 적지 마.
- 명령어는 실제 레포에서 동작하는 것만 적어줘.
- 불확실한 내용은 “확인 필요”라고 표시해줘.
- docs/TECH_SPEC.md와 실제 코드가 다르면 실제 구현 기준으로 문서를 업데이트하되, 큰 설계 변경이면 요약해서 알려줘.
- 테스트가 실패하면 실패 내용을 숨기지 말고 원인과 남은 TODO를 정리해줘.

수용 기준:
- 교수자가 업로드한 TXT 또는 PDF 자료를 처리할 수 있어야 한다.
- 처리 완료 후 DocumentChunk가 생성되어야 한다.
- 임베딩이 저장되어야 한다.
- 과목별 검색 API가 동작해야 한다.
- 검색 결과가 다른 과목 자료를 포함하지 않아야 한다.
- README에 3단계 실행/테스트 방법이 정리되어야 한다.
- docs/TECH_SPEC.md가 실제 구현과 맞게 업데이트되어야 한다.
- 4단계 챗봇 구현에 필요한 검색 API가 준비되어야 한다.

작업 후 출력:
- 최종 구현 기능 목록
- 테스트 완료 여부
- 실패한 테스트와 원인
- README 업데이트 요약
- TECH_SPEC 업데이트 요약
- 4단계로 넘어가기 전 확인해야 할 점
```

---

# 3단계 완료 기준

```text id="step3-done"
3단계는 아래 조건을 만족하면 완료로 본다.

1. CourseMaterial 처리 API가 존재한다.
2. pending 자료를 processing 상태로 전환하여 처리할 수 있다.
3. TXT 파일에서 텍스트를 추출할 수 있다.
4. PDF 파일에서 텍스트를 추출할 수 있다.
5. 추출된 텍스트가 DocumentChunk로 분할되어 저장된다.
6. 각 DocumentChunk에 course_id, material_id, chunk_index, page_number가 저장된다.
7. 각 DocumentChunk에 임베딩이 생성되어 저장된다.
8. local hash embedding으로 외부 API 없이 테스트할 수 있다.
9. VectorStoreService를 통해 유사 청크 검색이 가능하다.
10. 검색은 반드시 course_id 기준으로 제한된다.
11. POST /rag/search API가 동작한다.
12. GET /courses/{course_id}/rag/status API가 동작한다.
13. 교수자 화면에서 자료 처리 상태를 확인할 수 있다.
14. failed 자료를 재처리할 수 있다.
15. 처리 실패 사유가 processing_error에 저장된다.
16. 권한 없는 사용자는 자료 처리/검색을 수행할 수 없다.
17. README에 3단계 실행 및 테스트 방법이 정리되어 있다.
18. docs/TECH_SPEC.md가 실제 구현 상태와 맞게 업데이트되어 있다.
19. 4단계에서 챗봇 답변 생성 API가 바로 검색 API를 사용할 수 있다.
```

---

# 3단계 구현 시 주의할 점

```text id="step3-warnings"
1. RAG 검색은 반드시 과목 단위로 제한해야 한다.
2. 다른 과목의 DocumentChunk가 검색 결과에 섞이면 심각한 권한 문제다.
3. 임베딩 API Key 없이 local hash embedding으로 개발 가능해야 한다.
4. local hash embedding은 deterministic해야 한다.
5. 문서 처리 실패 시 processing_status가 processing에 멈추면 안 된다.
6. reprocess 시 기존 청크가 중복 저장되면 안 된다.
7. 긴 문서 본문을 서버 로그에 그대로 남기면 안 된다.
8. 스캔 PDF는 OCR 없이 처리하지 못할 수 있으므로 failed 처리해야 한다.
9. HWP는 MVP에서 무리해서 지원하지 말고 추후 검토로 남겨도 된다.
10. 3단계에서는 LLM 답변 생성까지 구현하지 않는다.
11. 3단계의 산출물은 “검색 가능한 지식베이스”다.
12. 챗봇 답변 생성, 출처 포함 답변, SAFE 응답 정책은 4단계에서 구현한다.
```
