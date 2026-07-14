from collections.abc import Generator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.security import JWTService
from app.db.session import get_db
from app.main import app
from app.models import Base, Course, CourseAccess, User, UserRole


@dataclass(frozen=True)
class RBACApiContext:
    client: TestClient
    tokens: dict[str, str]
    users: dict[str, str]
    courses: dict[str, str]


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
def rbac_api() -> Generator[RBACApiContext, None, None]:
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

    settings = get_settings()
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
    with TestClient(app) as client:
        yield RBACApiContext(
            client=client,
            tokens=tokens,
            users=user_ids,
            courses=course_ids,
        )
    app.dependency_overrides.clear()


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
