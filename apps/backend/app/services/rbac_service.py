from __future__ import annotations

from typing import Iterable, Sequence, Union

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Course, CourseAccess, User, UserRole

RoleInput = Union[UserRole, str]


class PermissionDeniedError(Exception):
    """Raised when an authenticated user is not allowed to perform an action."""


class CourseNotFoundError(Exception):
    """Raised when a course-scoped permission check targets a missing course."""


def role_value(role: RoleInput) -> str:
    if isinstance(role, UserRole):
        return role.value
    return role


def normalize_roles(roles: Union[RoleInput, Sequence[RoleInput]]) -> set[str]:
    role_items: Iterable[RoleInput]
    if isinstance(roles, (str, UserRole)):
        role_items = (roles,)
    else:
        role_items = roles

    normalized: set[str] = set()
    for role in role_items:
        value = role_value(role)
        normalized.add(UserRole(value).value)

    return normalized


def ensure_role(user: User, roles: Union[RoleInput, Sequence[RoleInput]]) -> User:
    allowed_roles = normalize_roles(roles)
    if role_value(user.role) not in allowed_roles:
        raise PermissionDeniedError

    return user


def get_course_or_raise(session: Session, course_id: str) -> Course:
    course = session.get(Course, course_id)
    if course is None:
        raise CourseNotFoundError

    return course


def student_has_course_access(session: Session, user: User, course: Course) -> bool:
    if not course.is_active:
        return False

    access_id = session.scalar(
        select(CourseAccess.id)
        .where(
            CourseAccess.course_id == course.id,
            CourseAccess.user_id == user.id,
        )
        .limit(1)
    )
    return access_id is not None


def can_access_course(session: Session, user: User, course: Course) -> bool:
    user_role = role_value(user.role)

    if user_role == UserRole.admin.value:
        return True
    if user_role == UserRole.professor.value:
        return course.professor_id == user.id
    if user_role == UserRole.student.value:
        return student_has_course_access(session, user, course)

    return False


def can_manage_course(user: User, course: Course) -> bool:
    user_role = role_value(user.role)

    if user_role == UserRole.admin.value:
        return True
    if user_role == UserRole.professor.value:
        return course.professor_id == user.id

    return False


def ensure_course_access(session: Session, user: User, course_id: str) -> Course:
    course = get_course_or_raise(session, course_id)
    if not can_access_course(session, user, course):
        raise PermissionDeniedError

    return course


def ensure_course_manage_permission(session: Session, user: User, course_id: str) -> Course:
    course = get_course_or_raise(session, course_id)
    if not can_manage_course(user, course):
        raise PermissionDeniedError

    return course


def list_accessible_courses(session: Session, user: User) -> list[Course]:
    user_role = role_value(user.role)
    statement = select(Course).order_by(Course.name)

    if user_role == UserRole.admin.value:
        return list(session.scalars(statement).all())
    if user_role == UserRole.professor.value:
        return list(
            session.scalars(statement.where(Course.professor_id == user.id)).all()
        )
    if user_role == UserRole.student.value:
        return list(
            session.scalars(
                statement.join(CourseAccess)
                .where(
                    Course.is_active.is_(True),
                    CourseAccess.user_id == user.id,
                )
                .order_by(Course.name)
            ).all()
        )

    return []
