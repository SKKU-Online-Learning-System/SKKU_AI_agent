from collections.abc import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Course, CourseAccess, User, UserRole
from app.services.rbac_service import (
    CourseNotFoundError,
    PermissionDeniedError,
    ensure_course_access,
    ensure_course_manage_permission,
    ensure_role,
    list_accessible_courses,
)


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
def rbac_context() -> Generator[tuple[Session, dict[str, User], dict[str, Course]], None, None]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        users = {
            "admin": add_user(session, "admin-rbac@skku.edu", UserRole.admin),
            "professor": add_user(session, "professor-rbac@skku.edu", UserRole.professor),
            "other_professor": add_user(
                session,
                "other-professor-rbac@skku.edu",
                UserRole.professor,
            ),
            "student": add_user(session, "student-rbac@skku.edu", UserRole.student),
        }
        courses = {
            "owned": Course(
                name="Owned Course",
                semester="2026-2",
                professor_id=users["professor"].id,
                is_active=True,
            ),
            "other": Course(
                name="Other Course",
                semester="2026-2",
                professor_id=users["other_professor"].id,
                is_active=True,
            ),
            "inactive": Course(
                name="Inactive Course",
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

        yield session, users, courses


def test_ensure_role_accepts_single_and_multiple_roles(
    rbac_context: tuple[Session, dict[str, User], dict[str, Course]],
) -> None:
    _session, users, _courses = rbac_context

    assert ensure_role(users["admin"], UserRole.admin) == users["admin"]
    assert ensure_role(users["professor"], ["admin", "professor"]) == users["professor"]

    with pytest.raises(PermissionDeniedError):
        ensure_role(users["student"], UserRole.admin)


def test_course_access_policy_matches_roles(
    rbac_context: tuple[Session, dict[str, User], dict[str, Course]],
) -> None:
    session, users, courses = rbac_context

    assert ensure_course_access(session, users["admin"], courses["other"].id) == courses["other"]
    assert ensure_course_access(session, users["professor"], courses["owned"].id) == courses["owned"]
    assert ensure_course_access(session, users["student"], courses["owned"].id) == courses["owned"]

    with pytest.raises(PermissionDeniedError):
        ensure_course_access(session, users["professor"], courses["other"].id)
    with pytest.raises(PermissionDeniedError):
        ensure_course_access(session, users["student"], courses["other"].id)
    with pytest.raises(PermissionDeniedError):
        ensure_course_access(session, users["student"], courses["inactive"].id)
    with pytest.raises(CourseNotFoundError):
        ensure_course_access(session, users["admin"], "missing-course")


def test_course_manage_policy_denies_students_and_non_owner_professors(
    rbac_context: tuple[Session, dict[str, User], dict[str, Course]],
) -> None:
    session, users, courses = rbac_context

    assert (
        ensure_course_manage_permission(session, users["admin"], courses["other"].id)
        == courses["other"]
    )
    assert (
        ensure_course_manage_permission(session, users["professor"], courses["owned"].id)
        == courses["owned"]
    )

    with pytest.raises(PermissionDeniedError):
        ensure_course_manage_permission(session, users["professor"], courses["other"].id)
    with pytest.raises(PermissionDeniedError):
        ensure_course_manage_permission(session, users["student"], courses["owned"].id)


def test_list_accessible_courses_filters_by_role(
    rbac_context: tuple[Session, dict[str, User], dict[str, Course]],
) -> None:
    session, users, courses = rbac_context

    assert {course.id for course in list_accessible_courses(session, users["admin"])} == {
        course.id for course in courses.values()
    }
    assert {course.id for course in list_accessible_courses(session, users["professor"])} == {
        courses["owned"].id,
        courses["inactive"].id,
    }
    assert {course.id for course in list_accessible_courses(session, users["student"])} == {
        courses["owned"].id,
    }
