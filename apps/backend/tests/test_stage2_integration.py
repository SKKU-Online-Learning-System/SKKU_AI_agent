from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.seed import seed_database
from app.db.session import get_db
from app.main import app
from app.models import (
    Base,
    Course,
    CourseAccess,
    CourseMaterial,
    CourseMaterialStatus,
    User,
    UserRole,
)


@dataclass(frozen=True)
class Stage2Api:
    client: TestClient
    session_factory: sessionmaker[Session]
    professor_id: str
    professor_course_id: str
    seeded_course_ids: frozenset[str]
    seeded_course_titles: frozenset[str]
    student_accessible_course_id: str
    inaccessible_course_id: str
    upload_dir: Path

    def login(self, email: str) -> str:
        response = self.client.post(
            "/api/auth/login",
            json={"email": email, "password": "password123"},
        )

        assert response.status_code == 200
        return response.json()["access_token"]

    @staticmethod
    def headers(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def get(self, path: str, token: str):
        return self.client.get(path, headers=self.headers(token))

    def post(self, path: str, token: str, payload: dict[str, object]):
        return self.client.post(path, headers=self.headers(token), json=payload)

    def patch(self, path: str, token: str, payload: dict[str, object] | None = None):
        return self.client.patch(path, headers=self.headers(token), json=payload)

    def upload(self, course_id: str, token: str, file_name: str, content: bytes):
        return self.client.post(
            f"/api/courses/{course_id}/materials",
            headers=self.headers(token),
            files={"file": (file_name, content, "text/plain")},
        )


@pytest.fixture
def stage2_api(tmp_path: Path) -> Generator[Stage2Api, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)

    with testing_session() as session:
        seed_database(session)
        professor = session.scalar(select(User).where(User.email == "professor@skku.edu"))
        student = session.scalar(select(User).where(User.email == "student@skku.edu"))
        assert professor is not None
        assert student is not None
        other_professor = User(
            name="Other Professor",
            email="other-professor@skku.edu",
            external_auth_id="external-other-professor",
            role=UserRole.professor,
        )
        session.add(other_professor)
        session.flush()
        inaccessible_course = Course(
            name="권한 없는 활성 과목",
            semester="2026-2",
            professor_id=other_professor.id,
            is_active=True,
        )
        session.add(inaccessible_course)
        session.commit()

        professor_id = professor.id
        seeded_courses = session.scalars(
            select(Course)
            .where(Course.professor_id == professor_id)
            .order_by(Course.name)
        ).all()
        seeded_course_ids = frozenset(course.id for course in seeded_courses)
        seeded_course_titles = frozenset(course.name for course in seeded_courses)
        student_accessible_course_id = session.scalar(
            select(Course.id)
            .join(Course.access_entries)
            .where(CourseAccess.user_id == student.id)
            .order_by(Course.name)
        )
        assert seeded_course_ids
        assert student_accessible_course_id in seeded_course_ids
        inaccessible_course_id = inaccessible_course.id

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    upload_dir = tmp_path / "uploads"
    settings = Settings(upload_dir=str(upload_dir), max_upload_size_bytes=4)
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, raise_server_exceptions=False) as client:
        yield Stage2Api(
            client=client,
            session_factory=testing_session,
            professor_id=professor_id,
            professor_course_id=student_accessible_course_id,
            seeded_course_ids=seeded_course_ids,
            seeded_course_titles=seeded_course_titles,
            student_accessible_course_id=student_accessible_course_id,
            inaccessible_course_id=inaccessible_course_id,
            upload_dir=upload_dir,
        )
    app.dependency_overrides.clear()


def test_stage2_admin_professor_student_flow(stage2_api: Stage2Api) -> None:
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
    admin_courses = stage2_api.get("/api/admin/courses", admin_token)
    assert admin_courses.status_code == 200
    assert course_id in {course["id"] for course in admin_courses.json()}

    updated = stage2_api.patch(
        f"/api/admin/courses/{course_id}",
        admin_token,
        {"description": "수정된 설명"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "수정된 설명"
    deactivated = stage2_api.patch(
        f"/api/admin/courses/{course_id}/deactivate",
        admin_token,
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["isActive"] is False
    activated = stage2_api.patch(
        f"/api/admin/courses/{course_id}/activate",
        admin_token,
    )
    assert activated.status_code == 200
    assert activated.json()["isActive"] is True
    refreshed_course = next(
        course
        for course in stage2_api.get("/api/admin/courses", admin_token).json()
        if course["id"] == course_id
    )
    assert refreshed_course["description"] == "수정된 설명"
    assert refreshed_course["isActive"] is True

    professor_courses = stage2_api.get("/api/courses", professor_token)
    assert professor_courses.status_code == 200
    assert {item["id"] for item in professor_courses.json()} == (
        stage2_api.seeded_course_ids | {course_id}
    )
    assert {item["title"] for item in professor_courses.json()} == (
        stage2_api.seeded_course_titles | {"통합 테스트 과목"}
    )
    assert stage2_api.inaccessible_course_id not in {
        item["id"] for item in professor_courses.json()
    }

    student_courses = stage2_api.get("/api/courses", student_token)
    assert student_courses.status_code == 200
    assert {item["id"] for item in student_courses.json()} == stage2_api.seeded_course_ids
    assert {item["title"] for item in student_courses.json()} == stage2_api.seeded_course_titles
    deactivated_accessible_course = stage2_api.patch(
        f"/api/admin/courses/{stage2_api.student_accessible_course_id}/deactivate",
        admin_token,
    )
    assert deactivated_accessible_course.status_code == 200
    assert deactivated_accessible_course.json()["isActive"] is False
    inactive_student_courses = stage2_api.get("/api/courses", student_token)
    assert inactive_student_courses.status_code == 200
    assert {item["id"] for item in inactive_student_courses.json()} == (
        stage2_api.seeded_course_ids - {stage2_api.student_accessible_course_id}
    )
    reactivated_accessible_course = stage2_api.patch(
        f"/api/admin/courses/{stage2_api.student_accessible_course_id}/activate",
        admin_token,
    )
    assert reactivated_accessible_course.status_code == 200
    assert reactivated_accessible_course.json()["isActive"] is True
    assert {item["id"] for item in stage2_api.get("/api/courses", student_token).json()} == (
        stage2_api.seeded_course_ids
    )

    uploaded = stage2_api.upload(
        stage2_api.professor_course_id,
        professor_token,
        "week1.txt",
        b"note",
    )
    assert uploaded.status_code == 202
    material = uploaded.json()
    assert material["processingStatus"] == "pending"
    with stage2_api.session_factory() as session:
        stored_material = session.get(CourseMaterial, material["id"])
        assert stored_material is not None
        assert stored_material.processing_status == CourseMaterialStatus.pending
        storage_path = Path(stored_material.storage_path)
        assert storage_path.is_file()
        assert stored_material.file_name != stored_material.original_file_name
        UUID(Path(stored_material.file_name).stem)
        stored_material.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        session.commit()

    second_uploaded = stage2_api.upload(
        stage2_api.professor_course_id,
        professor_token,
        "week2.txt",
        b"next",
    )
    assert second_uploaded.status_code == 202
    second_material = second_uploaded.json()
    with stage2_api.session_factory() as session:
        second_stored_material = session.get(CourseMaterial, second_material["id"])
        assert second_stored_material is not None
        second_storage_path = Path(second_stored_material.storage_path)
        assert second_storage_path.is_file()

    listed = stage2_api.get(
        f"/api/courses/{stage2_api.professor_course_id}/materials",
        professor_token,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [second_material["id"], material["id"]]
    assert stage2_api.upload(
        stage2_api.professor_course_id,
        student_token,
        "student.txt",
        b"note",
    ).status_code == 403
    student_delete = stage2_api.client.delete(
        f"/api/courses/{stage2_api.professor_course_id}/materials/{material['id']}",
        headers=stage2_api.headers(student_token),
    )
    assert student_delete.status_code == 403
    deleted = stage2_api.client.delete(
        f"/api/courses/{stage2_api.professor_course_id}/materials/{material['id']}",
        headers=stage2_api.headers(professor_token),
    )
    assert deleted.status_code == 204
    second_deleted = stage2_api.client.delete(
        f"/api/courses/{stage2_api.professor_course_id}/materials/{second_material['id']}",
        headers=stage2_api.headers(professor_token),
    )
    assert second_deleted.status_code == 204
    with stage2_api.session_factory() as session:
        assert session.get(CourseMaterial, material["id"]) is None
        assert session.get(CourseMaterial, second_material["id"]) is None
    assert not storage_path.exists()
    assert not second_storage_path.exists()

    other_course_upload = stage2_api.upload(
        stage2_api.inaccessible_course_id,
        professor_token,
        "denied.txt",
        b"note",
    )
    assert other_course_upload.status_code == 403
    assert stage2_api.get(
        f"/api/courses/{stage2_api.inaccessible_course_id}",
        professor_token,
    ).status_code == 403
    assert stage2_api.get(
        f"/api/courses/{stage2_api.inaccessible_course_id}/materials",
        professor_token,
    ).status_code == 403
    assert stage2_api.client.get("/api/admin/courses").status_code == 401
    assert stage2_api.get("/api/admin/courses", professor_token).status_code == 403
    assert stage2_api.get("/api/admin/courses", student_token).status_code == 403
    assert stage2_api.get(
        f"/api/courses/{stage2_api.inaccessible_course_id}",
        student_token,
    ).status_code == 403
    assert stage2_api.client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer malformed-token"},
    ).status_code == 401


@pytest.mark.parametrize(
    ("file_name", "content", "expected_detail"),
    [
        ("unsupported.exe", b"note", "Allowed file types: .pdf, .pptx, .docx, .txt"),
        ("empty.txt", b"", "Uploaded file must not be empty"),
        ("oversize.txt", b"large", "Uploaded file exceeds the 4 byte limit"),
    ],
)
def test_stage2_upload_rejects_invalid_files_without_residue(
    stage2_api: Stage2Api,
    file_name: str,
    content: bytes,
    expected_detail: str,
) -> None:
    professor_token = stage2_api.login("professor@skku.edu")

    response = stage2_api.upload(
        stage2_api.professor_course_id,
        professor_token,
        file_name,
        content,
    )

    assert response.status_code == 422
    assert response.json() == {"detail": expected_detail}
    with stage2_api.session_factory() as session:
        assert session.scalars(select(CourseMaterial)).all() == []
    assert [path for path in stage2_api.upload_dir.rglob("*") if path.is_file()] == []
