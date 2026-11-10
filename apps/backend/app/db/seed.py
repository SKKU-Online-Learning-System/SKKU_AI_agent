from __future__ import annotations

import sys
from argparse import ArgumentParser
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Course, CourseAccess, User, UserRole


@dataclass(frozen=True)
class UserSeed:
    name: str
    email: str
    school_id: str
    role: UserRole


@dataclass(frozen=True)
class CourseSeed:
    name: str
    semester: str
    description: str


@dataclass(frozen=True)
class SeedSummary:
    users: int
    courses: int
    course_access: int


USER_SEEDS = (
    UserSeed("SKKU Admin", "admin@skku.edu", "ADMIN001", UserRole.admin),
    UserSeed("SKKU Professor", "professor@skku.edu", "PROF001", UserRole.professor),
    UserSeed("SKKU Student", "student@skku.edu", "STUDENT001", UserRole.student),
)

COURSE_SEEDS = (
    CourseSeed(
        "인공지능개론",
        "2026-2",
        "인공지능의 기본 개념과 응용을 학습하는 과목입니다.",
    ),
    CourseSeed(
        "시계열데이터처리개론",
        "2026-2",
        "시계열 데이터의 전처리, 정상성, 예측 모델을 학습하는 과목입니다.",
    ),
)

# Earlier seeds used these names; an existing database is renamed in place.
RENAMED_COURSES = {"소프트웨어공학": "시계열데이터처리개론"}


def ensure_demo_password(user: User, hasher: PasswordHasher, password: str) -> None:
    password_matches = False
    if user.password_hash:
        try:
            password_matches = hasher.verify(user.password_hash, password)
        except (InvalidHashError, VerificationError):
            password_matches = False

    if not password_matches or hasher.check_needs_rehash(user.password_hash or ""):
        user.password_hash = hasher.hash(password)


def seed_database(session: Session, password: str) -> SeedSummary:
    hasher = PasswordHasher()

    with session.begin():
        users_by_email: dict[str, User] = {}
        for user_seed in USER_SEEDS:
            user = session.scalar(select(User).where(User.email == user_seed.email))
            if user is None:
                user = User(
                    name=user_seed.name,
                    email=user_seed.email,
                    school_id=user_seed.school_id,
                    role=user_seed.role,
                )
                session.add(user)

            user.name = user_seed.name
            user.school_id = user_seed.school_id
            user.role = user_seed.role
            user.external_auth_id = None
            ensure_demo_password(user, hasher, password)
            users_by_email[user.email] = user

        session.flush()
        professor = users_by_email["professor@skku.edu"]
        student = users_by_email["student@skku.edu"]

        courses: list[Course] = []
        for course_seed in COURSE_SEEDS:
            previous_names = [old for old, new in RENAMED_COURSES.items() if new == course_seed.name]
            course = session.scalar(
                select(Course).where(
                    Course.name.in_([course_seed.name, *previous_names]),
                    Course.semester == course_seed.semester,
                ).order_by((Course.name == course_seed.name).desc())
            )
            if course is None:
                course = Course(
                    name=course_seed.name,
                    semester=course_seed.semester,
                    professor_id=professor.id,
                )
                session.add(course)

            course.name = course_seed.name
            course.description = course_seed.description
            course.professor_id = professor.id
            course.is_active = True
            courses.append(course)

        session.flush()
        access_count = 0
        for course in courses:
            access = session.scalar(
                select(CourseAccess).where(
                    CourseAccess.course_id == course.id,
                    CourseAccess.user_id == student.id,
                )
            )
            if access is None:
                access = CourseAccess(course_id=course.id, user_id=student.id)
                session.add(access)

            access.access_role = "student"
            access_count += 1

    return SeedSummary(
        users=len(users_by_email),
        courses=len(courses),
        course_access=access_count,
    )


def main(*, only_if_empty: bool = False) -> int:
    settings = get_settings()
    if settings.app_env != "local":
        print("Seed refused: demo accounts are local development only.", file=sys.stderr)
        return 1
    password = settings.seed_password
    with SessionLocal() as session:
        try:
            if only_if_empty:
                if session.scalar(select(User.id).limit(1)) is not None:
                    print("Seed skipped: the database already contains users.")
                    return 0
                session.rollback()
            if not password:
                print("Seed failed. Set SEED_PASSWORD in .env.", file=sys.stderr)
                return 1
            summary = seed_database(session, password)
        except SQLAlchemyError as exc:
            session.rollback()
            print(
                "Seed failed. Run 'python -m alembic upgrade head' before seeding. "
                f"Database error: {exc}",
                file=sys.stderr,
            )
            return 1

    print(
        f"users={summary.users} "
        f"courses={summary.courses} "
        f"course_access={summary.course_access}"
    )
    return 0


if __name__ == "__main__":
    parser = ArgumentParser(description="Seed local demo accounts and courses.")
    parser.add_argument("--if-empty", action="store_true", help="Skip if users already exist.")
    raise SystemExit(main(only_if_empty=parser.parse_args().if_empty))
