from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.db.seed import seed_database
from app.db.session import get_db
from app.main import app
from app.models import Base, Course, CourseMaterial, CourseMaterialStatus, User, UserRole


@dataclass(frozen=True)
class Stage2Api:
    client: TestClient
    session_factory: sessionmaker[Session]
    professor_id: str
    professor_course_id: str
    inaccessible_course_id: str

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
        assert professor is not None
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
        professor_course_id = session.scalar(
            select(Course.id)
            .where(Course.professor_id == professor_id)
            .order_by(Course.name)
        )
        assert professor_course_id is not None
        inaccessible_course_id = inaccessible_course.id

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    settings = Settings(upload_dir=str(tmp_path / "uploads"), max_upload_size_bytes=1024)
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app, raise_server_exceptions=False) as client:
        yield Stage2Api(
            client=client,
            session_factory=testing_session,
            professor_id=professor_id,
            professor_course_id=professor_course_id,
            inaccessible_course_id=inaccessible_course_id,
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

    professor_courses = stage2_api.get("/api/courses", professor_token)
    assert professor_courses.status_code == 200
    assert all(item["instructorId"] == stage2_api.professor_id for item in professor_courses.json())

    student_courses = stage2_api.get("/api/courses", student_token)
    assert student_courses.status_code == 200
    assert {item["title"] for item in student_courses.json()} == {
        "인공지능개론",
        "소프트웨어공학",
    }

    uploaded = stage2_api.client.post(
        f"/api/courses/{stage2_api.professor_course_id}/materials",
        headers=stage2_api.headers(professor_token),
        files={"file": ("week1.txt", b"lecture notes", "text/plain")},
    )
    assert uploaded.status_code == 202
    material = uploaded.json()
    assert material["processingStatus"] == "pending"
    with stage2_api.session_factory() as session:
        stored_material = session.get(CourseMaterial, material["id"])
        assert stored_material is not None
        assert stored_material.processing_status == CourseMaterialStatus.pending

    listed = stage2_api.get(
        f"/api/courses/{stage2_api.professor_course_id}/materials",
        professor_token,
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [material["id"]]
    deleted = stage2_api.client.delete(
        f"/api/courses/{stage2_api.professor_course_id}/materials/{material['id']}",
        headers=stage2_api.headers(professor_token),
    )
    assert deleted.status_code == 204
    with stage2_api.session_factory() as session:
        assert session.get(CourseMaterial, material["id"]) is None

    other_course_upload = stage2_api.client.post(
        f"/api/courses/{stage2_api.inaccessible_course_id}/materials",
        headers=stage2_api.headers(professor_token),
        files={"file": ("denied.txt", b"denied", "text/plain")},
    )
    assert other_course_upload.status_code == 403
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
