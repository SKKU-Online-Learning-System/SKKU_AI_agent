import importlib.util
from typing import Any

from argon2 import PasswordHasher
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.models import Base, Course, CourseAccess, CourseMaterial, User, UserRole


def create_test_engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(
        dbapi_connection: Any,
        _connection_record: Any,
    ) -> None:
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def test_seed_is_idempotent_and_creates_expected_demo_data() -> None:
    assert importlib.util.find_spec("app.db.seed") is not None
    from app.db.seed import seed_database

    engine = create_test_engine()
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        first_summary = seed_database(session)
        second_summary = seed_database(session)

        assert first_summary.users == second_summary.users == 3
        assert first_summary.courses == second_summary.courses == 2
        assert first_summary.course_access == second_summary.course_access == 2
        assert session.scalar(select(func.count()).select_from(User)) == 3
        assert session.scalar(select(func.count()).select_from(Course)) == 2
        assert session.scalar(select(func.count()).select_from(CourseAccess)) == 2
        assert session.scalar(select(func.count()).select_from(CourseMaterial)) == 0

        users = session.scalars(select(User).order_by(User.email)).all()
        assert {user.email: user.role for user in users} == {
            "admin@skku.edu": UserRole.admin,
            "professor@skku.edu": UserRole.professor,
            "student@skku.edu": UserRole.student,
        }

        hasher = PasswordHasher()
        for user in users:
            assert user.password_hash is not None
            assert hasher.verify(user.password_hash, "password123")

        professor = session.scalar(select(User).where(User.email == "professor@skku.edu"))
        student = session.scalar(select(User).where(User.email == "student@skku.edu"))
        courses = session.scalars(select(Course).order_by(Course.name)).all()

        assert professor is not None
        assert student is not None
        assert [course.name for course in courses] == ["소프트웨어공학", "인공지능개론"]
        assert all(course.semester == "2026-2" for course in courses)
        assert all(course.professor_id == professor.id for course in courses)
        assert {access.course_id for access in student.course_accesses} == {
            course.id for course in courses
        }
