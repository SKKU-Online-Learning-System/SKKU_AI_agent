# 2단계 기능 통합 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 인증, 역할별 권한, 과목 관리, 교수자 자료 업로드, 학생 과목 조회를 실제 API와 웹 화면으로 연결하고 README만으로 재현 가능한 2단계를 완성한다.

**Architecture:** FastAPI 통합 테스트는 SQLite와 임시 업로드 디렉터리를 사용해 인증부터 파일 및 DB 지속성까지 검증한다. 자료 저장 책임은 독립 서비스로 분리하고 라우트는 권한과 트랜잭션을 조율한다. Next.js는 기존 인증 공급자와 공통 API 클라이언트를 재사용해 교수자 및 학생 화면을 실제 백엔드에 연결한다.

**Tech Stack:** Python 3.9+, FastAPI, SQLAlchemy 2, Pydantic Settings, Pytest, Next.js 16, React 18, TypeScript, Vitest, Testing Library, PostgreSQL 16, Alembic

## Global Constraints

- 제품 기준은 `docs/PRD.md`, 기술 기준은 `docs/TEC_SPEC.md`, 승인 설계는 `docs/superpowers/specs/2026-07-20-stage-2-integration-design.md`다.
- 백엔드는 Python 3.9 이상, 4칸 들여쓰기, Ruff 100자 제한을 지킨다.
- 프론트엔드는 2칸 들여쓰기, 큰따옴표, 세미콜론을 사용한다.
- 허용 업로드 확장자는 `.pdf`, `.pptx`, `.docx`, `.txt`다.
- 기본 파일당 최대 크기는 `20971520`바이트(20MB)다.
- 사용자 제공 파일명은 저장 경로로 사용하지 않고 UUID 내부 파일명을 사용한다.
- 새 `CourseMaterial.processing_status`는 `pending`이다.
- 문서 파싱, 청크 분할, 임베딩, RAG, 답변 생성, 출처, 로그/통계는 구현하지 않는다.
- 기존 사용자 변경을 보존하고 관련 없는 리팩터링을 하지 않는다.

---

## 파일 구조

- Create: `apps/backend/app/services/material_service.py`
  - 확장자/크기/빈 파일 검증과 UUID 파일 저장을 담당한다.
- Create: `apps/backend/tests/test_materials_api.py`
  - 자료 권한, 저장, 목록, 삭제, 검증 실패를 실제 DB와 임시 디렉터리로 검증한다.
- Create: `apps/backend/tests/test_stage2_integration.py`
  - 세 역할 로그인부터 관리자 CRUD, 교수자 업로드, 학생 필터링까지 한 흐름으로 검증한다.
- Modify: `apps/backend/app/core/config.py`
  - 업로드 루트와 최대 크기 설정을 제공한다.
- Modify: `apps/backend/app/schemas/domain.py`
  - 실제 `CourseMaterial` 응답 계약을 ORM 모델과 맞춘다.
- Modify: `apps/backend/app/api/routes/materials.py`
  - DB 기반 목록, 업로드, 삭제를 구현한다.
- Modify: `.env.example`
  - 업로드 설정 예시를 추가한다.
- Modify: `apps/frontend/app/lib/api.ts`
  - 과목 및 자료 API 타입과 함수를 추가한다.
- Modify: `apps/frontend/app/lib/api.test.ts`
  - 새 API 함수의 URL, 메서드, FormData, 인증 동작을 검증한다.
- Create: `apps/frontend/app/components/courses/course-list-client.tsx`
  - 교수자와 학생이 공유하는 과목 목록의 로딩, 오류, 빈 상태를 담당한다.
- Create: `apps/frontend/app/components/courses/course-list-client.test.tsx`
  - 역할별 제목과 API 결과 렌더링을 검증한다.
- Create: `apps/frontend/app/professor/materials/professor-materials-client.tsx`
  - 과목 선택, 업로드, 목록, 상태, 삭제 상호작용을 담당한다.
- Create: `apps/frontend/app/professor/materials/professor-materials-client.test.tsx`
  - 자료 관리 상호작용과 오류 표시를 검증한다.
- Modify: `apps/frontend/app/professor/courses/page.tsx`
  - 교수자 실제 과목 목록 컴포넌트를 사용한다.
- Modify: `apps/frontend/app/professor/materials/page.tsx`
  - 교수자 실제 자료 관리 컴포넌트를 사용한다.
- Modify: `apps/frontend/app/student/courses/page.tsx`
  - 학생 실제 과목 목록 컴포넌트를 사용한다.
- Modify: `apps/frontend/app/globals.css`
  - 새 표, 폼, 상태, 빈 화면의 기존 디자인 계열 스타일을 추가한다.
- Modify: `README.md`
  - 설치부터 수동 통합 검증 및 3단계 경계까지 통합한다.

---

### Task 1: 백엔드 자료 API를 테스트 우선으로 완성

**Files:**
- Create: `apps/backend/tests/test_materials_api.py`
- Create: `apps/backend/app/services/material_service.py`
- Modify: `apps/backend/app/core/config.py`
- Modify: `apps/backend/app/schemas/domain.py`
- Modify: `apps/backend/app/api/routes/materials.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `require_course_access`, `require_course_manage_permission`, `CourseMaterial`, `CourseMaterialStatus`, `get_db`, `Settings`
- Produces: `StoredUpload`, `MaterialValidationError`, `save_upload(file, course_id, upload_dir, max_size_bytes)`, `remove_stored_file(path)`, DB 기반 자료 GET/POST/DELETE API

- [ ] **Step 1: 백엔드 개발 의존성을 현재 가상환경에 설치**

Windows PowerShell:

```powershell
.\.venv\bin\python.exe -m pip install -e packages/ai_rag
.\.venv\bin\python.exe -m pip install -e "apps/backend[dev]"
```

Linux/macOS:

```bash
python -m pip install -e packages/ai_rag
python -m pip install -e "apps/backend[dev]"
```

Expected: `pytest`, `ruff`, FastAPI, SQLAlchemy import 성공.

- [ ] **Step 2: 자료 API 실패 테스트 작성**

`apps/backend/tests/test_materials_api.py`에 SQLite `StaticPool`, `tmp_path`,
`get_db` 및 `get_settings` override를 사용하는 fixture를 만든다. fixture에는 admin,
담당 교수, 다른 교수, 학생, 활성 담당 과목, 다른 교수 과목, 학생 접근 관계를 넣고
실제 `JWTService` 토큰을 만든다.

핵심 테스트는 다음 계약을 직접 확인한다.

```python
def test_professor_uploads_lists_and_deletes_material(material_api) -> None:
    uploaded = material_api.upload("professor", "owned", "week1.txt", b"note")
    assert uploaded.status_code == 201
    body = uploaded.json()
    assert body["courseId"] == material_api.courses["owned"]
    assert body["originalFileName"] == "week1.txt"
    assert body["fileType"] == "txt"
    assert body["fileSize"] == 4
    assert body["processingStatus"] == "pending"

    listed = material_api.client.get(
        f"/api/courses/{material_api.courses['owned']}/materials",
        headers=material_api.headers("professor"),
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]

    deleted = material_api.client.delete(
        f"/api/courses/{material_api.courses['owned']}/materials/{body['id']}",
        headers=material_api.headers("professor"),
    )
    assert deleted.status_code == 204
```

```python
@pytest.mark.parametrize(
    ("file_name", "content", "expected_detail"),
    [
        ("malware.exe", b"x", "Allowed file types: .pdf, .pptx, .docx, .txt"),
        ("empty.txt", b"", "Uploaded file must not be empty"),
        ("large.txt", b"12345", "Uploaded file exceeds the 4 byte limit"),
    ],
)
def test_upload_validation_rejects_invalid_files(
    material_api,
    file_name,
    content,
    expected_detail,
) -> None:
    response = material_api.upload("professor", "owned", file_name, content)
    assert response.status_code == 422
    assert response.json() == {"detail": expected_detail}
```

테스트 설정의 `MAX_UPLOAD_SIZE_BYTES`는 4로 낮춰 큰 메모리를 할당하지 않고 경계
동작을 검증한다. 추가 테스트는 다음을 각각 독립 함수로 작성한다.

- 다른 교수자 과목의 목록/업로드/삭제는 403
- 학생의 접근 가능한 과목 목록은 200, 업로드/삭제는 403
- 다른 과목 자료 ID 삭제는 404
- 잘못된 업로드 뒤 DB 행과 임시 파일이 없음
- 내부 파일명은 UUID 형식이고 원본 파일명과 다름
- 삭제 후 DB 행과 실제 파일이 모두 없음

- [ ] **Step 3: 자료 테스트를 실행해 올바른 실패 확인**

```powershell
.\.venv\bin\python.exe -m pytest apps/backend/tests/test_materials_api.py -q
```

Expected: 현 라우트가 DB에 저장하지 않고 삭제 API가 없으므로 FAIL.

- [ ] **Step 4: 업로드 설정과 응답 스키마 구현**

`Settings`에 다음 필드를 추가한다.

```python
upload_dir: str = "uploads"
max_upload_size_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
```

`CourseMaterialRead`는 내부 경로를 제외하고 다음 필드를 사용한다.

```python
class CourseMaterialRead(CamelModel):
    id: str
    course_id: str
    uploaded_by: str
    original_file_name: str
    file_type: str
    file_size: int
    processing_status: Literal["pending", "processing", "completed", "failed"]
    processing_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
```

`.env.example`에 다음을 추가한다.

```text
UPLOAD_DIR=uploads
MAX_UPLOAD_SIZE_BYTES=20971520
```

- [ ] **Step 5: 자료 저장 서비스 최소 구현**

`material_service.py` 공개 계약:

```python
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

ALLOWED_MATERIAL_EXTENSIONS = frozenset({".pdf", ".pptx", ".docx", ".txt"})
READ_CHUNK_SIZE = 1024 * 1024


class MaterialValidationError(ValueError):
    pass


@dataclass(frozen=True)
class StoredUpload:
    internal_file_name: str
    original_file_name: str
    file_type: str
    file_size: int
    storage_path: Path
```

`save_upload`는 `async def`로 청크를 읽고, 제한 초과 시 생성 중인 파일을 제거한 뒤
`MaterialValidationError`를 발생시킨다. `remove_stored_file`은 파일이 이미 없을 때도
성공해야 한다.

- [ ] **Step 6: DB 기반 자료 라우트 최소 구현**

라우트는 `Session`, `Settings`를 주입받고 `select(CourseMaterial)`로 목록을 조회한다.
업로드 성공 후 다음 ORM 행을 저장한다.

```python
material = CourseMaterial(
    course_id=course.id,
    uploaded_by=current_user.id,
    file_name=stored.internal_file_name,
    original_file_name=stored.original_file_name,
    file_type=stored.file_type,
    file_size=stored.file_size,
    storage_path=str(stored.storage_path),
    processing_status=CourseMaterialStatus.pending,
)
```

`MaterialValidationError`는 HTTP 422로 변환한다. DB 예외가 나면 rollback 후 저장
파일을 지우고 예외를 다시 발생시킨다. 삭제는 과목과 자료 ID를 함께 조회해 404
범위를 제한하고, DB commit 뒤 파일을 제거하며 HTTP 204를 반환한다.

- [ ] **Step 7: 자료 테스트 통과 확인**

```powershell
.\.venv\bin\python.exe -m pytest apps/backend/tests/test_materials_api.py -q
```

Expected: 모든 자료 테스트 PASS.

- [ ] **Step 8: 백엔드 회귀 테스트와 정적 검사**

```powershell
.\.venv\bin\python.exe -m pytest apps/backend/tests -q
.\.venv\bin\python.exe -m ruff check apps/backend
```

Expected: 0 failures, Ruff 0 errors.

- [ ] **Step 9: 작업 단위 커밋**

```bash
git add .env.example apps/backend/app apps/backend/tests/test_materials_api.py
git commit -m "Add persistent course material uploads"
```

---

### Task 2: 세 역할 백엔드 통합 흐름 고정

**Files:**
- Create: `apps/backend/tests/test_stage2_integration.py`

**Interfaces:**
- Consumes: 공개 HTTP API와 Seed 데이터 계약
- Produces: 2단계 완료 기준을 한 흐름으로 검증하는 회귀 테스트

- [ ] **Step 1: 통합 흐름 테스트 작성**

테스트 fixture는 `seed_database(session)`를 실제 호출한 뒤 두 번째 교수자와 권한
없는 활성 과목 하나를 추가한다. 세 Seed 계정은 실제 `/api/auth/login`으로
로그인한다.

```python
def test_stage2_admin_professor_student_flow(stage2_api) -> None:
    admin_token = stage2_api.login("admin@skku.edu")
    professor_token = stage2_api.login("professor@skku.edu")
    student_token = stage2_api.login("student@skku.edu")

    created = stage2_api.post(
        "/api/admin/courses",
        admin_token,
        {
            "name": "통합 테스트 과목",
            "semester": "2027-1",
            "professorId": stage2_api.professor_id,
            "isActive": True,
        },
    )
    assert created.status_code == 201

    course_id = created.json()["id"]
    assert stage2_api.patch(
        f"/api/admin/courses/{course_id}",
        admin_token,
        {"description": "수정된 설명"},
    ).status_code == 200
    assert stage2_api.patch(
        f"/api/admin/courses/{course_id}/deactivate",
        admin_token,
    ).json()["isActive"] is False
    assert stage2_api.patch(
        f"/api/admin/courses/{course_id}/activate",
        admin_token,
    ).json()["isActive"] is True

    professor_courses = stage2_api.get("/api/courses", professor_token).json()
    assert all(item["instructorId"] == stage2_api.professor_id for item in professor_courses)

    student_courses = stage2_api.get("/api/courses", student_token).json()
    assert {item["title"] for item in student_courses} == {
        "인공지능개론",
        "소프트웨어공학",
    }
```

같은 테스트 또는 별도 명확한 테스트에서 다음을 검증한다.

- 교수자 자료 업로드 응답과 DB의 `pending`
- 업로드 목록과 삭제
- 다른 교수자 과목 403
- 학생과 교수자의 `/api/admin/courses` 403
- 학생의 권한 없는 과목 상세 403
- 잘못된 JWT의 `/api/auth/me` 401

- [ ] **Step 2: 통합 테스트 실행**

```powershell
.\.venv\bin\python.exe -m pytest apps/backend/tests/test_stage2_integration.py -q
```

Expected: PASS. 실패하면 해당 동작을 가장 작은 테스트로 분리해 원인을 확인하고
최소 구현만 수정한다.

- [ ] **Step 3: 전체 백엔드 테스트 실행**

```powershell
.\.venv\bin\python.exe -m pytest apps/backend/tests -q
```

Expected: 0 failures.

- [ ] **Step 4: 작업 단위 커밋**

```bash
git add apps/backend/tests/test_stage2_integration.py
git commit -m "Test the complete stage 2 API flow"
```

---

### Task 3: 프론트엔드 과목 및 자료 API 클라이언트 추가

**Files:**
- Modify: `apps/frontend/app/lib/api.test.ts`
- Modify: `apps/frontend/app/lib/api.ts`

**Interfaces:**
- Consumes: `apiRequest<T>()`, 백엔드 camelCase 응답
- Produces: `CourseSummary`, `CourseMaterial`, `listCourses`, `listCourseMaterials`, `uploadCourseMaterial`, `deleteCourseMaterial`

- [ ] **Step 1: API 클라이언트 실패 테스트 작성**

기존 fetch mock 패턴을 재사용해 다음을 검증한다.

```typescript
it("uploads a material with FormData without forcing JSON content type", async () => {
  const file = new File(["notes"], "week1.txt", { type: "text/plain" });

  await uploadCourseMaterial("course-1", file);

  const [, options] = vi.mocked(fetch).mock.calls[0];
  expect(options?.method).toBe("POST");
  expect(options?.body).toBeInstanceOf(FormData);
  expect(new Headers(options?.headers).has("Content-Type")).toBe(false);
});
```

추가로 과목 목록 GET, 자료 목록 GET, 자료 삭제 DELETE URL을 각각 검증한다.

- [ ] **Step 2: 테스트 실패 확인**

```powershell
& "C:\Program Files\nodejs\npm.cmd" test --workspace @skku-course-agent/frontend -- app/lib/api.test.ts
```

Expected: 새 함수 export가 없어 FAIL.

- [ ] **Step 3: API 타입과 함수 최소 구현**

```typescript
export type CourseSummary = {
  id: string;
  code: string;
  title: string;
  term: string;
  instructorId: string;
  agentStatus: "draft" | "active" | "disabled";
  createdAt: string;
  updatedAt: string;
};

export type CourseMaterial = {
  id: string;
  courseId: string;
  uploadedBy: string;
  originalFileName: string;
  fileType: string;
  fileSize: number;
  processingStatus: "pending" | "processing" | "completed" | "failed";
  processingError?: string | null;
  createdAt: string;
  updatedAt: string;
};
```

```typescript
export function listCourses(): Promise<CourseSummary[]> {
  return apiRequest<CourseSummary[]>("/api/courses");
}

export function listCourseMaterials(courseId: string): Promise<CourseMaterial[]> {
  return apiRequest<CourseMaterial[]>(`/api/courses/${courseId}/materials`);
}

export function uploadCourseMaterial(
  courseId: string,
  file: File
): Promise<CourseMaterial> {
  const body = new FormData();
  body.set("file", file);
  return apiRequest<CourseMaterial>(`/api/courses/${courseId}/materials`, {
    body,
    method: "POST"
  });
}

export function deleteCourseMaterial(
  courseId: string,
  materialId: string
): Promise<void> {
  return apiRequest<void>(
    `/api/courses/${courseId}/materials/${materialId}`,
    { method: "DELETE" }
  );
}
```

- [ ] **Step 4: API 테스트와 타입 검사**

```powershell
& "C:\Program Files\nodejs\npm.cmd" test --workspace @skku-course-agent/frontend -- app/lib/api.test.ts
& "C:\Program Files\nodejs\npm.cmd" run typecheck --workspace @skku-course-agent/frontend
```

Expected: 해당 테스트 PASS, TypeScript 0 errors.

- [ ] **Step 5: 작업 단위 커밋**

```bash
git add apps/frontend/app/lib/api.ts apps/frontend/app/lib/api.test.ts
git commit -m "Add course material frontend API client"
```

---

### Task 4: 교수자 및 학생 화면을 실제 API에 연결

**Files:**
- Create: `apps/frontend/app/components/courses/course-list-client.tsx`
- Create: `apps/frontend/app/components/courses/course-list-client.test.tsx`
- Create: `apps/frontend/app/professor/materials/professor-materials-client.tsx`
- Create: `apps/frontend/app/professor/materials/professor-materials-client.test.tsx`
- Modify: `apps/frontend/app/professor/courses/page.tsx`
- Modify: `apps/frontend/app/professor/materials/page.tsx`
- Modify: `apps/frontend/app/student/courses/page.tsx`
- Modify: `apps/frontend/app/globals.css`

**Interfaces:**
- Consumes: Task 3의 `listCourses`, `listCourseMaterials`, `uploadCourseMaterial`, `deleteCourseMaterial`
- Produces: `<CourseListClient audience="professor" | "student" />`, `<ProfessorMaterialsClient />`

- [ ] **Step 1: 과목 목록 컴포넌트 실패 테스트 작성**

API 모듈을 mock하고 다음을 검증한다.

```typescript
it("renders courses returned for the current role", async () => {
  vi.mocked(listCourses).mockResolvedValue([
    {
      id: "course-1",
      code: "course-1",
      title: "인공지능개론",
      term: "2026-2",
      instructorId: "professor-1",
      agentStatus: "active",
      createdAt: "2026-07-20T00:00:00Z",
      updatedAt: "2026-07-20T00:00:00Z"
    }
  ]);

  render(<CourseListClient audience="student" />);

  expect(await screen.findByText("인공지능개론")).toBeInTheDocument();
  expect(screen.getByText("2026-2")).toBeInTheDocument();
});
```

빈 배열은 역할에 맞는 빈 상태를, rejected Promise는 `role="alert"` 오류를 표시하는
테스트를 추가한다.

- [ ] **Step 2: 교수자 자료 화면 실패 테스트 작성**

다음 흐름을 Testing Library로 검증한다.

- 담당 과목을 불러오고 첫 과목을 선택
- 선택 과목의 자료 목록 호출
- TXT 파일 선택 후 업로드 클릭
- 반환된 `pending` 자료를 목록에 추가
- 삭제 클릭 후 API 호출과 화면 제거
- 잘못된 확장자와 20MB 초과를 API 호출 전에 표시

상태 라벨 기대값은 `pending`=`처리 대기`, `processing`=`처리 중`,
`completed`=`처리 완료`, `failed`=`처리 실패`로 고정한다.

- [ ] **Step 3: 프론트엔드 테스트 실패 확인**

```powershell
& "C:\Program Files\nodejs\npm.cmd" test --workspace @skku-course-agent/frontend -- app/components/courses/course-list-client.test.tsx app/professor/materials/professor-materials-client.test.tsx
```

Expected: 컴포넌트가 없어 FAIL.

- [ ] **Step 4: 과목 목록 컴포넌트 최소 구현**

`CourseListClient`는 mount에서 `listCourses()`를 호출하고 `loading`, `courses`,
`errorMessage` 상태만 관리한다. `audience`에 따라 제목과 빈 상태 문구를 선택한다.
각 행에는 과목명, 학기, 에이전트 상태를 표시한다.

페이지 연결:

```tsx
export default function ProfessorCoursesPage() {
  return <CourseListClient audience="professor" />;
}
```

```tsx
export default function StudentCoursesPage() {
  return <CourseListClient audience="student" />;
}
```

- [ ] **Step 5: 교수자 자료 관리 컴포넌트 최소 구현**

컴포넌트는 다음 상태만 가진다.

```typescript
const [courses, setCourses] = useState<CourseSummary[]>([]);
const [selectedCourseId, setSelectedCourseId] = useState("");
const [materials, setMaterials] = useState<CourseMaterial[]>([]);
const [selectedFile, setSelectedFile] = useState<File | null>(null);
const [isLoading, setIsLoading] = useState(true);
const [isSubmitting, setIsSubmitting] = useState(false);
const [errorMessage, setErrorMessage] = useState<string | null>(null);
```

선택 파일 확장자는 `pdf`, `pptx`, `docx`, `txt`, 크기는 `20 * 1024 * 1024` 이하로
검사한다. 백엔드 `ApiError` 메시지를 `role="alert"`에 표시한다. 삭제 버튼은
성공 응답 뒤에만 목록에서 항목을 제거한다.

- [ ] **Step 6: 기존 디자인 계열 스타일 추가**

`globals.css`에 `.course-list-page`, `.course-table`, `.material-manager`,
`.material-upload-form`, `.material-status`, `.empty-state`를 추가한다. 기존 색상
변수와 버튼 스타일을 재사용하고 760px 이하에서는 표를 가로 스크롤 가능하게 한다.

- [ ] **Step 7: 컴포넌트 테스트와 전체 프론트 테스트**

```powershell
& "C:\Program Files\nodejs\npm.cmd" test --workspace @skku-course-agent/frontend
```

Expected: 모든 Vitest 테스트 PASS.

- [ ] **Step 8: 타입, 린트, 빌드 검사**

```powershell
& "C:\Program Files\nodejs\npm.cmd" run typecheck --workspaces --if-present
& "C:\Program Files\nodejs\npm.cmd" run lint
& "C:\Program Files\nodejs\npm.cmd" run build:frontend
```

Expected: 세 명령 모두 exit 0.

- [ ] **Step 9: 작업 단위 커밋**

```bash
git add apps/frontend/app
git commit -m "Connect professor and student course screens"
```

---

### Task 5: README를 2단계 실행 안내서로 통합

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: 실제 설정, Makefile, API, Seed, 화면 경로, 검증 명령
- Produces: 새 개발자가 처음부터 2단계를 실행하고 확인할 수 있는 단일 안내서

- [ ] **Step 1: README 요구사항 검사 스크립트를 먼저 실행**

변경 전 다음 검색으로 누락된 항목을 기록한다.

```powershell
rg -n "2단계|migrate|seed|admin@skku.edu|/professor/materials|MAX_UPLOAD_SIZE_BYTES|문서 파싱|수동 통합" README.md
```

Expected: 일부 항목이 없거나 오래된 “다음 단계” 설명만 존재.

- [ ] **Step 2: 기존 내용을 보존하며 README 재구성**

다음 제목을 정확히 포함한다.

```markdown
# SKKU Course Agent MVP
## 프로젝트 소개
## 2단계 구현 기능
## 기술 스택
## 프로젝트 구조
## 사전 요구사항
## 환경변수 설정
## PostgreSQL 실행
## 데이터베이스 마이그레이션
## Seed 데이터 생성
## 로컬 서버 실행
## 테스트 계정
## 역할별 접속 경로
## 주요 API
## 파일 업로드 제한
## 자동 테스트
## 2단계 수동 통합 테스트 체크리스트
## 아직 구현되지 않은 기능
## 3단계 연결 지점
```

Linux/macOS와 Windows PowerShell 명령을 분리한다. 테스트 계정 세 개와
`password123`, 예시 과목 두 개, 학생 접근 관계를 표로 명시한다.

역할별 접속 경로:

- 관리자: `/admin`, `/admin/courses`, `/admin/courses/new`
- 교수자: `/professor`, `/professor/courses`, `/professor/materials`
- 학생: `/student`, `/student/courses`

파일 제한에는 허용 확장자, 20MB, 빈 파일 거절, UUID 내부 파일명,
`processing_status=pending`, 기본 저장 위치를 포함한다.

수동 체크리스트는 사용자 요청의 관리자, 교수자, 학생, 권한, 파일 업로드 시나리오를
체크박스로 모두 포함한다.

3단계 미구현 목록은 문서 파싱, 청크 분할, 임베딩 생성, RAG 검색, 챗봇 답변 생성,
출처 기반 답변, 로그/통계 대시보드를 포함한다.

- [ ] **Step 3: README 명령과 코드 일치 검사**

```powershell
rg -n "UPLOAD_DIR|MAX_UPLOAD_SIZE_BYTES|20971520|pending|admin@skku.edu|professor@skku.edu|student@skku.edu|/api/courses/.*/materials" README.md .env.example apps/backend/app
```

Expected: 값과 경로가 일치하며 오래된 자료 API 상태명이 없음.

- [ ] **Step 4: 문서 diff 검사**

```powershell
git diff --check
git diff -- README.md
```

Expected: 공백 오류 없음, 기존 프로젝트 소개와 구조가 유지됨.

- [ ] **Step 5: 작업 단위 커밋**

```bash
git add README.md
git commit -m "Document the complete stage 2 workflow"
```

---

### Task 6: 전체 검증과 완료 기준 대조

**Files:**
- Verify: `apps/backend/tests`
- Verify: `apps/frontend`
- Verify: `packages/ai_rag/tests`
- Verify: `README.md`

**Interfaces:**
- Consumes: Tasks 1-5의 모든 결과
- Produces: 명령 출력에 근거한 최종 완료 보고

- [ ] **Step 1: 백엔드 전체 검증**

```powershell
.\.venv\bin\python.exe -m pytest apps/backend/tests -q
.\.venv\bin\python.exe -m ruff check apps/backend
```

Expected: 0 failures, 0 Ruff errors.

- [ ] **Step 2: AI/RAG 기존 회귀 테스트**

```powershell
.\.venv\bin\python.exe -m pytest packages/ai_rag/tests -q
```

Expected: 0 failures.

- [ ] **Step 3: 프론트엔드 전체 검증**

```powershell
& "C:\Program Files\nodejs\npm.cmd" test --workspace @skku-course-agent/frontend
& "C:\Program Files\nodejs\npm.cmd" run typecheck --workspaces --if-present
& "C:\Program Files\nodejs\npm.cmd" run lint
& "C:\Program Files\nodejs\npm.cmd" run build:frontend
```

Expected: 테스트 0 failures, 타입/린트/빌드 exit 0.

- [ ] **Step 4: 마이그레이션과 Seed 자동 검증**

```powershell
.\.venv\bin\python.exe -m pytest apps/backend/tests/test_migrations.py apps/backend/tests/test_seed.py -q
```

Expected: 마이그레이션 및 Seed 테스트 PASS.

- [ ] **Step 5: Git 상태 및 diff 점검**

```powershell
git status --short
git diff --check
git log -5 --oneline
```

Expected: 의도한 파일만 변경되고 공백 오류 없음.

- [ ] **Step 6: 완료 기준을 줄 단위로 대조**

최종 보고 전에 다음 12개 항목 각각에 테스트 또는 파일 근거를 연결한다.

1. 세 역할 로그인
2. JWT 인증
3. 역할별 페이지 접근 제한
4. 관리자 과목 CRUD 및 활성 상태
5. 교수자 담당 과목 필터
6. 교수자 담당 과목 자료 업로드
7. 학생 활성 접근 과목 필터
8. `CourseMaterial` DB 저장
9. `processing_status=pending`
10. 401/403
11. README 실행 및 테스트 계정
12. 3단계 문서 처리 경계

- [ ] **Step 7: 최종 작업 커밋**

검증 중 생긴 수정만 포함한다.

```bash
git add apps packages README.md .env.example
git commit -m "Complete stage 2 integration"
```

변경이 없으면 빈 커밋을 만들지 않는다.
