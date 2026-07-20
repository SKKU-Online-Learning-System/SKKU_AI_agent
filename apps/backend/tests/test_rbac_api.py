from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings, get_settings
from app.core.security import JWTService
from app.db.session import get_db
from app.main import app
from app.models import Base, Course, CourseAccess, CourseMaterial, User, UserRole


@dataclass(frozen=True)
class RBACApiContext:
    client: TestClient
    tokens: dict[str, str]
    users: dict[str, str]
    courses: dict[str, str]
    session_factory: sessionmaker[Session]
    upload_dir: Path


def add_user(session: Session, email: str, role: UserRole) -> User:
    user = User(
        name=email,
        email=email,
        external_auth_id=f"external-{email}",
        role=role,
    )
    session.add(user)
    session.flush()
    return user


@pytest.fixture
def rbac_api(tmp_path: Path) -> Generator[RBACApiContext, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)

    with testing_session() as session:
        users = {
            "admin": add_user(session, "admin-api@skku.edu", UserRole.admin),
            "professor": add_user(session, "professor-api@skku.edu", UserRole.professor),
            "other_professor": add_user(
                session,
                "other-professor-api@skku.edu",
                UserRole.professor,
            ),
            "student": add_user(session, "student-api@skku.edu", UserRole.student),
        }
        courses = {
            "owned": Course(
                name="Owned API Course",
                semester="2026-2",
                professor_id=users["professor"].id,
                is_active=True,
            ),
            "other": Course(
                name="Other API Course",
                semester="2026-2",
                professor_id=users["other_professor"].id,
                is_active=True,
            ),
            "inactive": Course(
                name="Inactive API Course",
                semester="2026-2",
                professor_id=users["professor"].id,
                is_active=False,
            ),
        }
        session.add_all(courses.values())
        session.flush()
        session.add_all(
            [
                CourseAccess(course_id=courses["owned"].id, user_id=users["student"].id),
                CourseAccess(course_id=courses["inactive"].id, user_id=users["student"].id),
            ]
        )
        session.commit()

        user_ids = {name: user.id for name, user in users.items()}
        course_ids = {name: course.id for name, course in courses.items()}

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as session:
            yield session

    repository_upload_dir = Path(__file__).resolve().parents[3] / "uploads"
    repository_files_before = (
        {
            path.relative_to(repository_upload_dir)
            for path in repository_upload_dir.rglob("*")
            if path.is_file()
        }
        if repository_upload_dir.exists()
        else set()
    )
    upload_dir = tmp_path / "uploads"
    settings = Settings(upload_dir=str(upload_dir), _env_file=None)
    token_service = JWTService(
        settings.jwt_secret,
        settings.jwt_algorithm,
        settings.jwt_expires_in,
    )
    tokens = {
        name: token_service.create_access_token(user_id)
        for name, user_id in user_ids.items()
    }

    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield RBACApiContext(
            client=client,
            tokens=tokens,
            users=user_ids,
            courses=course_ids,
            session_factory=testing_session,
            upload_dir=upload_dir,
        )
    app.dependency_overrides.clear()
    repository_files_after = (
        {
            path.relative_to(repository_upload_dir)
            for path in repository_upload_dir.rglob("*")
            if path.is_file()
        }
        if repository_upload_dir.exists()
        else set()
    )
    assert repository_files_after == repository_files_before


def auth_headers(context: RBACApiContext, user_name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.tokens[user_name]}"}


def test_admin_api_requires_admin_role(rbac_api: RBACApiContext) -> None:
    no_auth = rbac_api.client.get("/api/admin/stats")
    student = rbac_api.client.get(
        "/api/admin/stats",
        headers=auth_headers(rbac_api, "student"),
    )
    admin = rbac_api.client.get(
        "/api/admin/stats",
        headers=auth_headers(rbac_api, "admin"),
    )

    assert no_auth.status_code == 401
    assert student.status_code == 403
    assert admin.status_code == 200


def test_course_detail_enforces_course_access(rbac_api: RBACApiContext) -> None:
    owned_course = f"/api/courses/{rbac_api.courses['owned']}"
    other_course = f"/api/courses/{rbac_api.courses['other']}"

    assert (
        rbac_api.client.get(owned_course, headers=auth_headers(rbac_api, "admin")).status_code
        == 200
    )
    assert (
        rbac_api.client.get(
            owned_course,
            headers=auth_headers(rbac_api, "professor"),
        ).status_code
        == 200
    )
    assert (
        rbac_api.client.get(owned_course, headers=auth_headers(rbac_api, "student")).status_code
        == 200
    )
    assert (
        rbac_api.client.get(
            other_course,
            headers=auth_headers(rbac_api, "professor"),
        ).status_code
        == 403
    )
    assert (
        rbac_api.client.get(other_course, headers=auth_headers(rbac_api, "student")).status_code
        == 403
    )
    assert (
        rbac_api.client.get(
            "/api/courses/missing-course",
            headers=auth_headers(rbac_api, "admin"),
        ).status_code
        == 404
    )


def test_course_list_returns_only_accessible_courses(rbac_api: RBACApiContext) -> None:
    admin_response = rbac_api.client.get(
        "/api/courses",
        headers=auth_headers(rbac_api, "admin"),
    )
    professor_response = rbac_api.client.get(
        "/api/courses",
        headers=auth_headers(rbac_api, "professor"),
    )
    student_response = rbac_api.client.get(
        "/api/courses",
        headers=auth_headers(rbac_api, "student"),
    )

    assert admin_response.status_code == 200
    assert professor_response.status_code == 200
    assert student_response.status_code == 200
    assert {course["id"] for course in admin_response.json()} == set(rbac_api.courses.values())
    assert {course["id"] for course in professor_response.json()} == {
        rbac_api.courses["owned"],
        rbac_api.courses["inactive"],
    }
    assert {course["id"] for course in student_response.json()} == {
        rbac_api.courses["owned"],
    }


def test_course_list_and_detail_include_persisted_instructor_name(
    rbac_api: RBACApiContext,
) -> None:
    student_list = rbac_api.client.get(
        "/api/courses",
        headers=auth_headers(rbac_api, "student"),
    )
    student_detail = rbac_api.client.get(
        f"/api/courses/{rbac_api.courses['owned']}",
        headers=auth_headers(rbac_api, "student"),
    )
    created = rbac_api.client.post(
        "/api/courses",
        headers=auth_headers(rbac_api, "admin"),
        json={
            "code": "SEC101",
            "title": "Secure Contracts",
            "term": "2027-1",
            "instructorId": rbac_api.users["professor"],
            "instructorName": "Spoofed Client Name",
            "agentStatus": "active",
        },
    )

    assert student_list.status_code == 200
    assert student_list.json()[0]["instructorName"] == "professor-api@skku.edu"
    assert student_detail.status_code == 200
    assert student_detail.json()["instructorName"] == "professor-api@skku.edu"
    assert created.status_code == 201
    assert created.json()["instructorName"] == "professor-api@skku.edu"


def test_material_upload_requires_course_manage_permission(rbac_api: RBACApiContext) -> None:
    def upload_as(user_name: str, course_name: str):
        return rbac_api.client.post(
            f"/api/courses/{rbac_api.courses[course_name]}/materials",
            headers=auth_headers(rbac_api, user_name),
            data={"title": "Week 1"},
            files={"file": ("week1.txt", b"notes", "text/plain")},
        )

    professor_own = upload_as("professor", "owned")
    professor_other = upload_as("professor", "other")
    student_own = upload_as("student", "owned")
    admin_other = upload_as("admin", "other")

    assert professor_own.status_code == 202
    assert professor_own.json()["uploadedBy"] == rbac_api.users["professor"]
    assert professor_other.status_code == 403
    assert student_own.status_code == 403
    assert admin_other.status_code == 202
    assert admin_other.json()["uploadedBy"] == rbac_api.users["admin"]
    with rbac_api.session_factory() as session:
        stored_paths = [
            Path(material.storage_path).resolve()
            for material in session.scalars(select(CourseMaterial)).all()
        ]
    assert stored_paths
    assert all(path.is_relative_to(rbac_api.upload_dir.resolve()) for path in stored_paths)


def test_chat_session_requires_course_access(rbac_api: RBACApiContext) -> None:
    allowed = rbac_api.client.post(
        "/api/chat/sessions",
        headers=auth_headers(rbac_api, "student"),
        json={
            "userId": "client-supplied-user-id-is-ignored",
            "courseId": rbac_api.courses["owned"],
            "title": "Study",
        },
    )
    denied = rbac_api.client.post(
        "/api/chat/sessions",
        headers=auth_headers(rbac_api, "student"),
        json={
            "userId": rbac_api.users["student"],
            "courseId": rbac_api.courses["other"],
            "title": "Study",
        },
    )

    assert allowed.status_code == 201
    assert allowed.json()["userId"] == rbac_api.users["student"]
    assert denied.status_code == 403
