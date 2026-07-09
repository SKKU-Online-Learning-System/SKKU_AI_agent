# Codex용 2단계 세부 개발 프롬프트

## 사용 순서

```text id="n2v0ux"
2-0. 현재 프로젝트 상태 점검
2-1. DB 스키마 / 마이그레이션 / Seed 데이터
2-2. 인증 API / JWT 로그인
2-3. Backend 권한 관리 / RBAC 미들웨어
2-4. Frontend 인증 상태 / 라우트 보호 / 역할별 메뉴
2-5. 관리자 과목 관리 기능
2-6. 교수자 담당 과목 조회 / 강의자료 업로드
2-7. 학생 과목 목록 / 접근 가능한 과목 조회
2-8. 오류 처리 / 검증 / 빈 상태 UI 정리
2-9. 2단계 통합 테스트 / README 업데이트
```

---

# 2-0. 현재 프로젝트 상태 점검 프롬프트

```text id="codex-step2-0"
너는 이 프로젝트의 시니어 풀스택 개발자야.

지금부터 “코스 에이전트 MVP”의 2단계 기능을 구현하려고 한다.

2단계의 목표는 다음과 같다.

- 사용자 인증
- 역할 기반 권한 관리
- 과목 관리
- 교수자 강의자료 업로드
- 학생/교수자/관리자 역할별 기본 화면 제공

먼저 현재 레포지토리 상태를 점검해줘.

해야 할 일:
1. 프로젝트 구조를 확인해줘.
2. 사용 중인 프론트엔드/백엔드/DB/ORM/패키지 매니저를 파악해줘.
3. 이미 존재하는 인증, 사용자, 과목, 파일 업로드 관련 코드가 있는지 확인해줘.
4. 2단계 구현에 필요한 파일 목록을 정리해줘.
5. 기존 코드 스타일과 네이밍 컨벤션을 파악해줘.
6. 불필요한 대규모 리팩토링은 하지 말고, 현재 구조를 최대한 유지해줘.
7. 아직 코드를 수정하지 말고 분석 결과만 정리해줘.

출력 형식:
- 현재 기술 스택
- 주요 폴더 구조
- 이미 구현된 기능
- 없는 기능
- 2단계 구현 계획
- 예상 수정 파일 목록
- 주의해야 할 기존 코드
```

---

# 2-1. DB 스키마 / 마이그레이션 / Seed 데이터 프롬프트

```text id="codex-step2-1"
이제 2단계의 DB 스키마와 기본 Seed 데이터를 구현해줘.

목표:
- 사용자, 역할, 과목, 과목 접근 권한, 강의자료 메타데이터를 저장할 수 있는 DB 구조를 만든다.
- 이후 인증, 권한 관리, 과목 관리, 자료 업로드 기능에서 바로 사용할 수 있게 한다.

구현해야 할 주요 엔티티:

1. User
   - id
   - name
   - email
   - password_hash 또는 외부 인증 식별자
   - school_id
   - role
   - created_at
   - updated_at

2. Role
   - MVP에서는 별도 테이블이 아니라 enum으로 처리해도 된다.
   - 허용 값:
     - student
     - professor
     - admin

3. Course
   - id
   - name
   - semester
   - description
   - professor_id
   - is_active
   - created_at
   - updated_at

4. CourseEnrollment 또는 CourseAccess
   - id
   - course_id
   - user_id
   - access_role
   - created_at

   설명:
   - 학생이 접근 가능한 과목을 관리하기 위한 테이블이다.
   - professor_id만으로 교수자 접근을 처리해도 되지만, 학생 수강 과목은 별도 관계 테이블이 필요하다.

5. CourseMaterial
   - id
   - course_id
   - uploaded_by
   - file_name
   - original_file_name
   - file_type
   - file_size
   - storage_path
   - processing_status
   - processing_error
   - created_at
   - updated_at

   processing_status 값:
   - pending
   - processing
   - completed
   - failed

주의:
- RAG 처리, 임베딩, DocumentChunk는 3단계에서 구현한다.
- 2단계에서는 자료 업로드 메타데이터 저장까지만 구현한다.
- 실제 문서 파싱이나 임베딩 생성은 하지 않는다.
- 기존 ORM이 있으면 그 방식을 따라가고, 없으면 현재 프로젝트에 적합한 방식을 선택해줘.
- 마이그레이션 파일이 필요한 구조라면 마이그레이션도 만들어줘.

Seed 데이터:
1. 관리자 계정
   - email: admin@skku.edu
   - password: password123
   - role: admin

2. 교수자 계정
   - email: professor@skku.edu
   - password: password123
   - role: professor

3. 학생 계정
   - email: student@skku.edu
   - password: password123
   - role: student

4. 예시 과목
   - 인공지능개론
   - 소프트웨어공학

5. 예시 접근 관계
   - professor@skku.edu는 두 과목의 담당 교수자
   - student@skku.edu는 두 과목에 접근 가능

수용 기준:
- DB 마이그레이션 또는 스키마 생성이 정상 동작해야 한다.
- Seed 실행 후 admin/professor/student 계정이 생성되어야 한다.
- Seed 실행 후 예시 과목 2개가 생성되어야 한다.
- CourseMaterial은 아직 파일이 없어도 테이블 구조가 준비되어야 한다.

작업 후 출력:
- 생성/수정한 파일 목록
- DB 스키마 설명
- Seed 실행 방법
- 테스트 방법
```

---

# 2-2. 인증 API / JWT 로그인 프롬프트

```text id="codex-step2-2"
이제 사용자 인증 기능을 구현해줘.

목표:
- 사용자가 이메일과 비밀번호로 로그인할 수 있다.
- 로그인 성공 시 JWT access token을 발급한다.
- 현재 로그인한 사용자 정보를 조회할 수 있다.
- 이후 학교 계정 또는 LMS 연동으로 교체 가능하도록 인증 구조를 분리한다.

구현해야 할 API:

1. POST /auth/login
   입력:
   - email
   - password

   처리:
   - email로 사용자 조회
   - 비밀번호 검증
   - 성공 시 JWT 발급
   - 사용자 기본 정보 반환

   응답 예시:
   {
     "access_token": "...",
     "token_type": "bearer",
     "user": {
       "id": "...",
       "name": "...",
       "email": "...",
       "role": "student"
     }
   }

2. GET /auth/me
   처리:
   - Authorization Bearer token 검증
   - 현재 사용자 정보 반환

3. POST /auth/logout
   - JWT 기반이면 서버에서 특별히 처리하지 않아도 된다.
   - 프론트엔드에서 토큰을 삭제하는 방식이면 API는 생략 가능하다.
   - 다만 클라이언트 구조에서 필요하면 빈 응답으로 구현해도 된다.

보안 요구사항:
- 비밀번호는 평문 저장 금지
- password_hash 사용
- JWT_SECRET은 환경변수에서 읽기
- 토큰 만료 시간을 설정
- 잘못된 로그인 정보는 구체적으로 “이메일이 틀림/비밀번호가 틀림”을 분리해서 노출하지 말 것

주의:
- 실제 학교 SSO 연동은 MVP 범위가 아니다.
- 하지만 나중에 SSO로 교체할 수 있도록 auth service 계층을 분리해줘.
- 기존 프로젝트의 API 스타일을 유지해줘.

Frontend는 아직 최소한만 연결해도 된다.
이 프롬프트에서는 Backend 인증 API 구현을 우선한다.

수용 기준:
- Seed 계정으로 로그인 가능해야 한다.
- 로그인 성공 시 JWT가 반환되어야 한다.
- JWT로 /auth/me 호출 시 현재 사용자 정보가 반환되어야 한다.
- 잘못된 토큰은 401을 반환해야 한다.
- 잘못된 이메일/비밀번호는 401을 반환해야 한다.

작업 후 출력:
- 구현한 API 목록
- 인증 흐름 설명
- 환경변수 목록
- curl 또는 HTTP 테스트 예시
```

---

# 2-3. Backend 권한 관리 / RBAC 미들웨어 프롬프트

```text id="codex-step2-3"
이제 Backend에 역할 기반 접근 제어, 즉 RBAC 기능을 구현해줘.

역할:
- student
- professor
- admin

목표:
- API마다 접근 가능한 역할을 제한한다.
- 교수자는 본인 담당 과목에만 접근할 수 있다.
- 학생은 본인이 접근 가능한 활성화 과목에만 접근할 수 있다.
- 관리자는 전체 리소스에 접근할 수 있다.

구현해야 할 공통 기능:

1. get_current_user
   - JWT에서 사용자 ID 추출
   - DB에서 사용자 조회
   - 없으면 401 반환

2. require_role
   - 특정 역할만 API 접근 가능하게 하는 미들웨어 또는 dependency 구현
   - 예:
     - require_role("admin")
     - require_role(["admin", "professor"])

3. require_course_access
   - course_id 기준 접근 권한 확인
   - admin: 모든 과목 접근 가능
   - professor: 본인이 professor_id로 등록된 과목만 접근 가능
   - student: CourseEnrollment 또는 CourseAccess에 등록된 활성 과목만 접근 가능

4. require_course_manage_permission
   - 과목 수정/자료 업로드 권한 확인
   - admin: 가능
   - professor: 본인 담당 과목만 가능
   - student: 불가능

적용해야 할 기본 정책:

1. 관리자 API
   - admin만 접근 가능

2. 교수자 API
   - professor 또는 admin 접근 가능
   - 단, professor는 담당 과목만 접근 가능

3. 학생 API
   - student, professor, admin 모두 접근 가능할 수 있으나
   - 학생용 과목 접근은 CourseAccess 기준으로 제한

에러 응답:
- 인증되지 않은 사용자: 401
- 인증은 되었지만 권한 없음: 403
- 존재하지 않는 리소스: 404

주의:
- 권한 체크 로직을 각 API마다 중복 작성하지 말고 helper나 middleware로 분리해줘.
- 이후 로그 조회, 자료 업로드, 챗봇 API에서도 재사용 가능해야 한다.
- 테스트하기 쉽게 권한 체크 함수는 단위 테스트 가능한 구조로 만들어줘.

수용 기준:
- admin은 모든 과목에 접근 가능해야 한다.
- professor는 본인 담당 과목에만 접근 가능해야 한다.
- professor가 다른 교수자의 과목에 접근하면 403이어야 한다.
- student는 접근 등록된 활성 과목만 조회 가능해야 한다.
- 권한 없는 사용자는 관리자 API에 접근할 수 없어야 한다.

작업 후 출력:
- 구현한 미들웨어/helper 목록
- 권한 정책 설명
- 적용된 API 목록
- 테스트 방법
```

---

# 2-4. Frontend 인증 상태 / 라우트 보호 / 역할별 메뉴 프롬프트

```text id="codex-step2-4"
이제 Frontend에 인증 상태 관리와 역할별 라우트 보호를 구현해줘.

목표:
- 사용자가 로그인할 수 있다.
- 로그인 후 역할에 따라 다른 화면으로 이동한다.
- 역할에 따라 접근 가능한 메뉴가 달라진다.
- 권한 없는 페이지 접근은 차단한다.

구현해야 할 화면:

1. 로그인 화면
   경로 예시:
   - /login

   기능:
   - email 입력
   - password 입력
   - 로그인 버튼
   - 로그인 실패 메시지 표시
   - 로그인 성공 시 access_token 저장
   - /auth/me로 사용자 정보 조회 또는 로그인 응답의 user 사용

2. 역할별 기본 이동
   - admin → /admin
   - professor → /professor
   - student → /student

3. 공통 레이아웃
   - 현재 사용자 이름 표시
   - 현재 역할 표시
   - 로그아웃 버튼
   - 역할별 메뉴 표시

4. Protected Route
   - 로그인하지 않은 사용자는 /login으로 이동
   - 권한 없는 역할이 특정 페이지에 접근하면 403 페이지 또는 대시보드로 이동

5. 역할별 메뉴
   admin:
   - 관리자 대시보드
   - 과목 관리
   - 사용자 관리
   - 자료 관리

   professor:
   - 교수자 대시보드
   - 담당 과목
   - 자료 업로드

   student:
   - 학생 대시보드
   - 내 과목
   - 챗봇

주의:
- 아직 모든 페이지의 실제 기능이 없어도 된다.
- 최소한 라우팅과 권한 보호가 동작해야 한다.
- access_token 저장 방식은 현재 프로젝트 관례를 따르되, 가능하면 보안상 안전한 방식을 선택해줘.
- API 호출 모듈에 Authorization 헤더를 자동으로 붙이는 구조를 만들어줘.
- 새로고침해도 로그인 상태가 복원되도록 해줘.

수용 기준:
- 로그인 성공 시 역할에 맞는 페이지로 이동해야 한다.
- student는 /admin에 접근할 수 없어야 한다.
- professor는 /admin에 접근할 수 없어야 한다.
- admin은 관리자 페이지에 접근 가능해야 한다.
- 로그아웃 시 토큰이 삭제되고 /login으로 이동해야 한다.
- 새로고침 후에도 /auth/me를 통해 로그인 상태가 유지되어야 한다.

작업 후 출력:
- 구현한 화면 목록
- 인증 상태 관리 방식
- 라우트 보호 방식
- 테스트 방법
```

---

# 2-5. 관리자 과목 관리 기능 프롬프트

```text id="codex-step2-5"
이제 관리자 과목 관리 기능을 구현해줘.

목표:
- 관리자는 과목을 생성, 조회, 수정, 비활성화할 수 있다.
- 교수자를 과목 담당자로 지정할 수 있다.
- 학생 접근 권한은 최소한 조회 또는 추후 확장 가능한 구조로 만들어둔다.

Backend API:

1. GET /admin/courses
   - 관리자만 가능
   - 전체 과목 목록 조회
   - 필터 옵션:
     - semester
     - is_active
     - professor_id
     - keyword

2. POST /admin/courses
   - 관리자만 가능
   - 과목 생성

   입력:
   - name
   - semester
   - description
   - professor_id
   - is_active

3. GET /admin/courses/{course_id}
   - 관리자만 가능
   - 과목 상세 조회

4. PATCH /admin/courses/{course_id}
   - 관리자만 가능
   - 과목 정보 수정

5. PATCH /admin/courses/{course_id}/deactivate
   - 관리자만 가능
   - 과목 비활성화

6. PATCH /admin/courses/{course_id}/activate
   - 관리자만 가능
   - 과목 활성화

Frontend 화면:

1. /admin/courses
   - 과목 목록 테이블
   - 과목명
   - 학기
   - 담당 교수
   - 활성화 여부
   - 생성일
   - 수정 버튼
   - 활성화/비활성화 버튼

2. /admin/courses/new
   - 과목 생성 폼

3. /admin/courses/[courseId] 또는 모달
   - 과목 상세 및 수정 폼

폼 필드:
- 과목명
- 학기
- 설명
- 담당 교수자
- 활성화 여부

주의:
- 담당 교수자는 role이 professor인 사용자 중에서 선택하게 해줘.
- 교수자 목록 API가 필요하면 GET /admin/users?role=professor 형태로 구현해도 된다.
- 과목 삭제는 MVP에서 물리 삭제 대신 비활성화로 처리해줘.
- 학생 수강생 등록은 이번 프롬프트에서 필수 구현하지 않아도 되지만, CourseAccess 구조와 충돌하지 않게 설계해줘.

수용 기준:
- admin 계정으로 과목 목록을 볼 수 있어야 한다.
- admin 계정으로 새 과목을 생성할 수 있어야 한다.
- admin 계정으로 과목 정보를 수정할 수 있어야 한다.
- admin 계정으로 과목을 활성화/비활성화할 수 있어야 한다.
- student/professor 계정은 관리자 과목 API에 접근할 수 없어야 한다.

작업 후 출력:
- 구현한 API 목록
- 구현한 화면 목록
- 과목 비활성화 처리 방식
- 테스트 방법
```

---

# 2-6. 교수자 담당 과목 조회 / 강의자료 업로드 프롬프트

```text id="codex-step2-6"
이제 교수자 기능 중 담당 과목 조회와 강의자료 업로드 기능을 구현해줘.

목표:
- 교수자는 본인이 담당하는 과목 목록을 볼 수 있다.
- 교수자는 본인 담당 과목에 강의자료를 업로드할 수 있다.
- 관리자는 모든 과목에 자료를 업로드할 수 있다.
- 업로드된 파일은 CourseMaterial 메타데이터로 저장된다.
- 실제 문서 파싱과 RAG 인덱싱은 3단계에서 처리하므로, 이번 단계에서는 processing_status를 pending으로 저장한다.

Backend API:

1. GET /professor/courses
   - professor 또는 admin 접근 가능
   - professor는 본인 담당 과목만 반환
   - admin은 전체 또는 요청된 교수자의 과목 반환 가능

2. GET /courses/{course_id}/materials
   - 해당 과목 접근 권한 필요
   - 교수자는 본인 담당 과목 자료 조회 가능
   - 관리자는 모든 과목 자료 조회 가능
   - 학생은 일단 자료 목록 조회를 제한하거나, 공개 자료만 조회 가능하게 해도 된다.

3. POST /courses/{course_id}/materials
   - professor 또는 admin 가능
   - professor는 본인 담당 과목만 가능
   - multipart/form-data 파일 업로드
   - 업로드 후 CourseMaterial 생성
   - processing_status는 pending으로 저장

4. DELETE /courses/{course_id}/materials/{material_id}
   - professor 또는 admin 가능
   - professor는 본인 담당 과목 자료만 삭제 가능
   - 실제 파일 삭제 또는 soft delete 중 현재 구조에 맞게 선택

지원 파일:
- 우선 TXT, PDF
- 가능하면 PPTX, DOCX 확장자도 저장은 허용하되 파싱은 3단계 TODO로 남겨도 됨

파일 검증:
- 허용 확장자만 업로드 가능
- 파일 크기 제한 설정
- 빈 파일 업로드 방지
- 업로드 실패 시 명확한 오류 메시지 반환

Frontend 화면:

1. /professor/courses
   - 담당 과목 목록
   - 과목명
   - 학기
   - 활성화 여부
   - 자료 수
   - 자료 관리 버튼

2. /professor/courses/[courseId]/materials
   - 과목명 표시
   - 파일 업로드 영역
   - 업로드된 자료 목록
   - 파일명
   - 파일 형식
   - 파일 크기
   - 처리 상태
   - 업로드 일시
   - 삭제 버튼

주의:
- 교수자가 다른 교수자의 과목에 업로드하려고 하면 403이어야 한다.
- 관리자도 같은 API를 사용할 수 있게 해도 된다.
- 파일 저장 경로는 환경변수 또는 설정으로 분리해줘.
- 파일명 충돌을 피하기 위해 내부 저장 파일명은 UUID 기반으로 만들어줘.
- 원본 파일명은 original_file_name으로 따로 저장해줘.
- 3단계에서 문서 처리 파이프라인을 연결할 수 있도록 CourseMaterial 구조를 깔끔하게 유지해줘.

수용 기준:
- professor 계정은 본인 담당 과목 목록을 볼 수 있어야 한다.
- professor 계정은 본인 담당 과목에 파일을 업로드할 수 있어야 한다.
- professor 계정은 다른 교수 과목에 업로드할 수 없어야 한다.
- admin 계정은 모든 과목에 파일 업로드 가능해야 한다.
- 업로드된 파일 메타데이터가 DB에 저장되어야 한다.
- 파일의 processing_status는 pending이어야 한다.
- 업로드된 자료 목록이 화면에 표시되어야 한다.

작업 후 출력:
- 구현한 API 목록
- 구현한 화면 목록
- 파일 저장 방식
- CourseMaterial 저장 구조
- 테스트 방법
```

---

# 2-7. 학생 과목 목록 / 접근 가능한 과목 조회 프롬프트

```text id="codex-step2-7"
이제 학생용 과목 목록 기능을 구현해줘.

목표:
- 학생은 본인이 접근 가능한 활성화 과목만 볼 수 있다.
- 학생은 비활성화된 과목이나 접근 권한이 없는 과목을 볼 수 없다.
- 이후 4단계 챗봇 기능에서 선택할 수 있는 과목 목록의 기반을 만든다.

Backend API:

1. GET /student/courses
   - student 접근 가능
   - 현재 로그인한 학생이 CourseAccess 또는 CourseEnrollment로 연결된 과목만 반환
   - is_active = true인 과목만 반환

2. GET /student/courses/{course_id}
   - student 접근 가능
   - 본인이 접근 가능한 활성화 과목만 상세 조회 가능
   - 접근 권한이 없으면 403 또는 404
   - 비활성화 과목이면 접근 불가

3. 공통 GET /courses/{course_id}
   - 역할별 권한 체크를 적용해도 된다.
   - student: 본인 접근 과목만
   - professor: 담당 과목만
   - admin: 전체 과목

Frontend 화면:

1. /student/courses
   - 내 과목 목록
   - 과목명
   - 학기
   - 담당 교수
   - 설명
   - 활성 상태
   - 챗봇 시작 버튼 또는 “준비 중” 버튼

2. /student/courses/[courseId]
   - 과목 상세 정보
   - 담당 교수
   - 과목 설명
   - 챗봇 진입 버튼
   - 아직 챗봇 기능은 4단계이므로 버튼은 disabled 또는 placeholder 처리 가능

주의:
- 학생이 모든 과목 목록을 볼 수 있으면 안 된다.
- 학생이 URL을 직접 입력해 접근 권한 없는 과목을 조회할 수 없어야 한다.
- 챗봇 API는 아직 구현하지 않는다.
- 자료 다운로드나 자료 목록 공개는 MVP 정책이 확정되지 않았으므로 기본적으로 학생에게는 숨겨도 된다.

수용 기준:
- student 계정은 본인이 등록된 활성 과목만 볼 수 있어야 한다.
- 비활성화 과목은 목록에 나오지 않아야 한다.
- 접근 권한 없는 course_id에 직접 접근하면 차단되어야 한다.
- professor/admin 계정으로 학생 페이지 접근 시 정책에 따라 차단하거나 역할별 대시보드로 보낸다.

작업 후 출력:
- 구현한 API 목록
- 구현한 화면 목록
- 학생 과목 접근 권한 처리 방식
- 테스트 방법
```

---

# 2-8. 오류 처리 / 검증 / 빈 상태 UI 정리 프롬프트

```text id="codex-step2-8"
이제 2단계 기능 전반의 오류 처리, 입력 검증, 빈 상태 UI를 정리해줘.

목표:
- 인증, 과목 관리, 자료 업로드에서 사용자가 이해할 수 있는 오류 메시지를 제공한다.
- API 응답 형식을 일관되게 만든다.
- 프론트엔드 화면에서 로딩/오류/빈 상태를 명확히 보여준다.

Backend 작업:

1. 공통 에러 응답 형식 정리
   예시:
   {
     "error": {
       "code": "COURSE_NOT_FOUND",
       "message": "과목을 찾을 수 없습니다."
     }
   }

2. 주요 에러 코드 정의
   - UNAUTHORIZED
   - FORBIDDEN
   - VALIDATION_ERROR
   - USER_NOT_FOUND
   - INVALID_CREDENTIALS
   - COURSE_NOT_FOUND
   - COURSE_ACCESS_DENIED
   - MATERIAL_NOT_FOUND
   - INVALID_FILE_TYPE
   - FILE_TOO_LARGE
   - FILE_UPLOAD_FAILED

3. 입력 검증
   로그인:
   - email 필수
   - password 필수

   과목 생성/수정:
   - name 필수
   - semester 필수
   - professor_id 유효성 확인

   파일 업로드:
   - 파일 필수
   - 허용 확장자 확인
   - 파일 크기 제한 확인
   - 빈 파일 방지

4. 권한 에러 구분
   - 로그인 안 됨: 401
   - 로그인했지만 권한 없음: 403
   - 리소스 없음: 404
   - 입력 오류: 400 또는 422

Frontend 작업:

1. 공통 API 에러 처리
   - API 클라이언트에서 에러 메시지를 파싱
   - 사용자에게 표시 가능한 메시지로 변환

2. 로딩 상태
   - 로그인 중
   - 과목 목록 불러오는 중
   - 파일 업로드 중
   - 과목 저장 중

3. 빈 상태
   - 등록된 과목이 없습니다.
   - 업로드된 자료가 없습니다.
   - 접근 가능한 과목이 없습니다.

4. 오류 상태
   - 로그인 실패
   - 권한 없음
   - 파일 업로드 실패
   - 과목 저장 실패

5. 403/404 페이지
   - 권한 없는 접근
   - 존재하지 않는 페이지 또는 리소스

주의:
- 에러 메시지는 한국어로 제공해줘.
- 개발자용 상세 에러는 콘솔 또는 로그에 남기되, 사용자에게 내부 스택트레이스를 보여주지 마.
- API 응답 형식을 과도하게 바꾸면 기존 코드가 깨질 수 있으므로 영향 범위를 확인해줘.

수용 기준:
- 잘못된 로그인 시 명확한 실패 메시지가 보여야 한다.
- 권한 없는 API 접근 시 403이 반환되어야 한다.
- 잘못된 파일 형식 업로드 시 사용자에게 안내가 보여야 한다.
- 과목 목록이 비어 있으면 빈 상태 메시지가 보여야 한다.
- 로딩 상태가 주요 화면에 표시되어야 한다.

작업 후 출력:
- 정의한 에러 코드 목록
- 검증 규칙 목록
- 수정한 UI 상태 목록
- 테스트 방법
```

---

# 2-9. 2단계 통합 테스트 / README 업데이트 프롬프트

```text id="codex-step2-9"
이제 2단계 기능을 통합 테스트하고 README를 업데이트해줘.

목표:
- 인증, 권한, 과목 관리, 교수자 자료 업로드, 학생 과목 조회가 하나의 흐름으로 정상 동작하는지 확인한다.
- 로컬에서 다른 개발자가 README만 보고 2단계 기능을 실행하고 테스트할 수 있게 한다.

테스트해야 할 시나리오:

1. Seed 데이터 생성
   - admin@skku.edu
   - professor@skku.edu
   - student@skku.edu
   - 예시 과목 2개
   - 학생 과목 접근 관계

2. 관리자 시나리오
   - admin 로그인
   - 관리자 대시보드 접근
   - 과목 목록 조회
   - 과목 생성
   - 과목 수정
   - 과목 비활성화
   - 과목 활성화

3. 교수자 시나리오
   - professor 로그인
   - 교수자 대시보드 접근
   - 담당 과목 목록 조회
   - 담당 과목 자료 업로드
   - 업로드 자료 목록 조회
   - 자료 삭제
   - 다른 교수자 과목 접근 시 403 확인

4. 학생 시나리오
   - student 로그인
   - 학생 대시보드 접근
   - 접근 가능한 과목 목록 조회
   - 비활성화 과목이 보이지 않는지 확인
   - 접근 권한 없는 과목 URL 직접 접근 시 차단 확인

5. 권한 시나리오
   - student가 /admin 접근 시 차단
   - professor가 /admin 접근 시 차단
   - 미로그인 사용자가 보호 페이지 접근 시 /login 이동
   - 잘못된 JWT로 API 호출 시 401

6. 파일 업로드 시나리오
   - 허용된 파일 업로드 성공
   - 허용되지 않은 확장자 업로드 실패
   - 빈 파일 업로드 실패
   - 너무 큰 파일 업로드 실패
   - 업로드된 CourseMaterial의 processing_status가 pending인지 확인

README에 추가할 내용:

1. 프로젝트 소개
2. 2단계 구현 기능 목록
3. 기술 스택
4. 환경변수 설정
5. DB 실행 방법
6. 마이그레이션 방법
7. Seed 데이터 생성 방법
8. 로컬 서버 실행 방법
9. 테스트 계정 정보
10. 역할별 접속 경로
11. 주요 API 목록
12. 파일 업로드 제한
13. 아직 구현되지 않은 기능
    - 문서 파싱
    - 임베딩 생성
    - RAG 검색
    - 챗봇 답변 생성
    - 출처 기반 답변
    - 로그/통계 대시보드

가능하면 자동 테스트도 추가해줘.
우선순위:
1. 권한 체크 테스트
2. 인증 API 테스트
3. 과목 CRUD 테스트
4. 파일 업로드 테스트

주의:
- 테스트가 너무 오래 걸리거나 현재 구조에서 어렵다면, 최소한 수동 테스트 체크리스트를 README에 명확히 작성해줘.
- 기존 README가 있으면 덮어쓰지 말고 필요한 내용을 통합해줘.
- 실행되지 않는 테스트 코드를 억지로 만들지 말고, 실제로 실행 가능한 수준으로 작성해줘.

수용 기준:
- README만 보고 로컬에서 2단계 기능을 실행할 수 있어야 한다.
- 세 역할 계정으로 로그인 테스트가 가능해야 한다.
- 관리자/교수자/학생 각각의 핵심 기능이 동작해야 한다.
- 권한 없는 접근이 차단되어야 한다.
- 업로드된 자료가 CourseMaterial로 저장되어야 한다.
- 3단계에서 이어서 문서 처리/RAG 기능을 붙일 수 있는 상태여야 한다.

작업 후 출력:
- 최종 구현 기능 목록
- 테스트 완료 여부
- 남은 TODO
- README 업데이트 내용 요약
- 3단계로 넘어가기 전 확인해야 할 점
```

---

# 2단계 완료 기준

```text id="step2-done"
2단계는 아래 조건을 만족하면 완료로 본다.

1. admin, professor, student 계정으로 로그인할 수 있다.
2. JWT 기반 인증이 동작한다.
3. 역할별 페이지 접근 제한이 동작한다.
4. admin은 과목을 생성, 수정, 활성화, 비활성화할 수 있다.
5. professor는 본인 담당 과목만 볼 수 있다.
6. professor는 본인 담당 과목에 강의자료를 업로드할 수 있다.
7. student는 본인이 접근 가능한 활성 과목만 볼 수 있다.
8. CourseMaterial 메타데이터가 DB에 저장된다.
9. 업로드 자료의 processing_status가 pending으로 저장된다.
10. 권한 없는 접근은 401 또는 403으로 차단된다.
11. README에 실행 방법과 테스트 계정이 정리되어 있다.
12. 3단계에서 문서 파싱, 청크 분할, 임베딩, 검색 기능을 이어서 붙일 수 있다.
```
