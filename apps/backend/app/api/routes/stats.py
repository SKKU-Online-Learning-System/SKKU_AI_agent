"""Role-scoped MVP usage statistics."""

from __future__ import annotations

import re
from collections import Counter
from typing import Annotated, Iterable

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.db.session import get_db
from app.models import ChatLog, ChatSession, Course, CourseAccess, CourseMaterial, User, UserRole
from app.services.rbac_service import can_manage_course

router = APIRouter(prefix="/stats", tags=["statistics"])

WORD_PATTERN = re.compile(r"[0-9A-Za-z가-힣]{2,}")
STOP_WORDS = frozenset({"그리고", "대한", "무엇", "설명", "알려줘", "어떻게", "있나요", "해주세요"})


def _count(session: Session, model: type, *conditions: object) -> int:
    statement = select(func.count()).select_from(model)
    if conditions:
        statement = statement.where(*conditions)
    return int(session.scalar(statement) or 0)


def _course_rows(session: Session, professor_id: str | None = None) -> list[dict[str, object]]:
    question_count = (
        select(func.count(ChatLog.id))
        .where(ChatLog.course_id == Course.id)
        .correlate(Course)
        .scalar_subquery()
    )
    user_count = (
        select(func.count(CourseAccess.id))
        .where(CourseAccess.course_id == Course.id)
        .correlate(Course)
        .scalar_subquery()
    )
    material_count = (
        select(func.count(CourseMaterial.id))
        .where(CourseMaterial.course_id == Course.id)
        .correlate(Course)
        .scalar_subquery()
    )
    statement = select(Course, question_count, user_count, material_count).order_by(Course.name)
    if professor_id:
        statement = statement.where(Course.professor_id == professor_id)

    return [
        {
            "courseId": course.id,
            "courseName": course.name,
            "questionCount": int(questions or 0),
            "userCount": int(users or 0),
            "materialCount": int(materials or 0),
        }
        for course, questions, users, materials in session.execute(statement).all()
    ]


def _questions_by_date(session: Session, *conditions: object) -> list[dict[str, object]]:
    day = func.date(ChatLog.created_at)
    statement = select(day, func.count(ChatLog.id)).group_by(day).order_by(day)
    if conditions:
        statement = statement.where(*conditions)
    return [{"date": str(value), "count": int(count)} for value, count in session.execute(statement)]


def _recent_questions(session: Session, *conditions: object) -> list[dict[str, object]]:
    statement = (
        select(ChatLog, Course.name)
        .join(Course, Course.id == ChatLog.course_id)
        .order_by(ChatLog.created_at.desc())
        .limit(10)
    )
    if conditions:
        statement = statement.where(*conditions)
    return [
        {
            "id": log.id,
            "courseId": log.course_id,
            "courseName": course_name,
            "question": log.question,
            "createdAt": log.created_at,
        }
        for log, course_name in session.execute(statement)
    ]


def _keywords(questions: Iterable[str]) -> list[dict[str, object]]:
    counts = Counter(
        word.lower()
        for question in questions
        for word in WORD_PATTERN.findall(question)
        if word not in STOP_WORDS
    )
    return [{"keyword": word, "count": count} for word, count in counts.most_common(10)]


def _question_texts(session: Session, *conditions: object) -> list[str]:
    # ponytail: cap the simple in-process analysis; use DB text search if 1,000 recent rows is insufficient.
    statement = select(ChatLog.question).order_by(ChatLog.created_at.desc()).limit(1000)
    if conditions:
        statement = statement.where(*conditions)
    return list(session.scalars(statement))


@router.get("/service")
def service_statistics(
    session: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_role(UserRole.admin))],
) -> dict[str, object]:
    """Return totals and course/date breakdowns for administrators."""

    return {
        "totals": {
            "courseCount": _count(session, Course),
            "userCount": _count(session, User),
            "questionCount": _count(session, ChatLog),
        },
        "questionsByDate": _questions_by_date(session),
        "courses": _course_rows(session),
    }


@router.get("/courses/{course_id}")
def course_statistics(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role([UserRole.admin, UserRole.professor]))],
) -> dict[str, object]:
    """Return one course's aggregate statistics without exposing student identities."""

    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    if not can_manage_course(current_user, course):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    summary = next(row for row in _course_rows(session) if row["courseId"] == course_id)
    condition = ChatLog.course_id == course_id
    return {
        **summary,
        "questionsByDate": _questions_by_date(session, condition),
        "recentQuestions": _recent_questions(session, condition),
        "keywords": _keywords(_question_texts(session, condition)),
    }


@router.get("/professor")
def professor_statistics(
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.professor))],
) -> dict[str, object]:
    """Return statistics limited to the professor's assigned courses."""

    condition = Course.professor_id == current_user.id
    log_condition = ChatLog.course_id.in_(select(Course.id).where(condition))
    return {
        "courses": _course_rows(session, current_user.id),
        "questionsByDate": _questions_by_date(session, log_condition),
        "recentQuestions": _recent_questions(session, condition),
        "keywords": _keywords(_question_texts(session, log_condition)),
    }


@router.get("/me")
def my_statistics(
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    """Return only the authenticated user's own usage."""

    rows = session.execute(
        select(Course.id, Course.name, func.count(ChatLog.id))
        .join(ChatLog, ChatLog.course_id == Course.id)
        .where(ChatLog.user_id == current_user.id)
        .group_by(Course.id, Course.name)
        .order_by(Course.name)
    )
    return {
        "questionCount": _count(session, ChatLog, ChatLog.user_id == current_user.id),
        "sessionCount": _count(session, ChatSession, ChatSession.user_id == current_user.id),
        "questionsByDate": _questions_by_date(session, ChatLog.user_id == current_user.id),
        "courses": [
            {"courseId": course_id, "courseName": name, "questionCount": int(count)}
            for course_id, name, count in rows
        ],
    }
