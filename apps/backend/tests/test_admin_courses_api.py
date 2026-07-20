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
class AdminCourseContext:
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
def admin_course_api() -> Generator[AdminCourseContext, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(engine)

    with testing_session() as session:
        users = {
            "admin": add_user(session, "admin-courses@skku.edu", UserRole.admin),
            "professor": add_user(session, "professor-courses@skku.edu", UserRole.professor),
            "other_professor": add_user(
                session,
                "other-professor-courses@skku.edu",
                UserRole.professor,
            ),
            "student": add_user(session, "student-courses@skku.edu", UserRole.student),
        }
        courses = {
            "active": Course(
                name="Artificial Intelligence",
                semester="2026-2",
                description="AI concepts",
                professor_id=users["professor"].id,
                is_active=True,
            ),
            "inactive": Course(
                name="Software Engineering",
                semester="2026-1",
                description="SWE process",
                professor_id=users["other_professor"].id,
                is_active=False,
            ),
        }
        session.add_all(courses.values())
        session.flush()
        session.add(CourseAccess(course_id=courses["active"].id, user_id=users["student"].id))
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
        yield AdminCourseContext(
            client=client,
            tokens=tokens,
            users=user_ids,
            courses=course_ids,
        )
    app.dependency_overrides.clear()


def auth_headers(context: AdminCourseContext, user_name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.tokens[user_name]}"}


def test_admin_course_api_rejects_non_admin_roles(
    admin_course_api: AdminCourseContext,
) -> None:
    for user_name in ("student", "professor"):
        response = admin_course_api.client.get(
            "/api/admin/courses",
            headers=auth_headers(admin_course_api, user_name),
        )
        assert response.status_code == 403


def test_admin_can_list_courses_with_filters_and_professor_metadata(
    admin_course_api: AdminCourseContext,
) -> None:
    response = admin_course_api.client.get(
        "/api/admin/courses",
        headers=auth_headers(admin_course_api, "admin"),
    )
    active_response = admin_course_api.client.get(
        "/api/admin/courses?is_active=true&keyword=Artificial",
        headers=auth_headers(admin_course_api, "admin"),
    )

    assert response.status_code == 200
    assert {course["id"] for course in response.json()} == set(admin_course_api.courses.values())
    assert active_response.status_code == 200
    assert [course["id"] for course in active_response.json()] == [
        admin_course_api.courses["active"]
    ]
    assert active_response.json()[0]["professorName"] == "professor-courses@skku.edu"
    assert active_response.json()[0]["studentAccessCount"] == 1


def test_admin_can_create_update_deactivate_and_activate_course(
    admin_course_api: AdminCourseContext,
) -> None:
    created = admin_course_api.client.post(
        "/api/admin/courses",
        headers=auth_headers(admin_course_api, "admin"),
        json={
            "name": "Machine Learning",
            "semester": "2027-1",
            "description": "ML basics",
            "professorId": admin_course_api.users["professor"],
            "isActive": True,
        },
    )

    assert created.status_code == 201
    course_id = created.json()["id"]
    assert created.json()["name"] == "Machine Learning"

    updated = admin_course_api.client.patch(
        f"/api/admin/courses/{course_id}",
        headers=auth_headers(admin_course_api, "admin"),
        json={
            "name": "Applied Machine Learning",
            "professorId": admin_course_api.users["other_professor"],
            "isActive": False,
        },
    )
    deactivated = admin_course_api.client.patch(
        f"/api/admin/courses/{course_id}/deactivate",
        headers=auth_headers(admin_course_api, "admin"),
    )
    activated = admin_course_api.client.patch(
        f"/api/admin/courses/{course_id}/activate",
        headers=auth_headers(admin_course_api, "admin"),
    )

    assert updated.status_code == 200
    assert updated.json()["name"] == "Applied Machine Learning"
    assert updated.json()["professorId"] == admin_course_api.users["other_professor"]
    assert updated.json()["isActive"] is False
    assert deactivated.status_code == 200
    assert deactivated.json()["isActive"] is False
    assert activated.status_code == 200
    assert activated.json()["isActive"] is True


def test_admin_course_api_validates_professor_and_exposes_access_list(
    admin_course_api: AdminCourseContext,
) -> None:
    bad_professor = admin_course_api.client.post(
        "/api/admin/courses",
        headers=auth_headers(admin_course_api, "admin"),
        json={
            "name": "Invalid Course",
            "semester": "2027-1",
            "professorId": admin_course_api.users["student"],
            "isActive": True,
        },
    )
    professors = admin_course_api.client.get(
        "/api/admin/users?role=professor",
        headers=auth_headers(admin_course_api, "admin"),
    )
    access = admin_course_api.client.get(
        f"/api/admin/courses/{admin_course_api.courses['active']}/access",
        headers=auth_headers(admin_course_api, "admin"),
    )

    assert bad_professor.status_code == 422
    assert professors.status_code == 200
    assert {user["id"] for user in professors.json()} == {
        admin_course_api.users["professor"],
        admin_course_api.users["other_professor"],
    }
    assert access.status_code == 200
    assert access.json()[0]["userId"] == admin_course_api.users["student"]
