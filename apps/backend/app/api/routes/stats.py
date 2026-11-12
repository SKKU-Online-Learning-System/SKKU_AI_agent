"""Role-scoped MVP usage statistics."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models import (
    ChatLog,
    ChatSession,
    Course,
    CourseAccess,
    CourseMaterial,
    LoginEvent,
    User,
    UserRole,
)
from app.services.question_keywords import DEFAULT_TERMS, CourseKeywordCounts, course_keyword_counts
from app.services.rbac_service import can_manage_course

router = APIRouter(prefix="/stats", tags=["statistics"])


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
    _current_user: Annotated[User, Depends(require_role(UserRole.admin))],
) -> dict[str, object]:
    """Return one course's aggregate statistics without exposing student identities."""

    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    summary = next(row for row in _course_rows(session) if row["courseId"] == course_id)
    condition = ChatLog.course_id == course_id
    return {
        **summary,
        "questionsByDate": _questions_by_date(session, condition),
    }


@router.get("/professor")
def professor_statistics(
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(UserRole.professor))],
) -> dict[str, object]:
    """Return statistics limited to the professor's assigned courses."""

    return {
        "courses": [
            {field: row[field] for field in ("courseId", "courseName", "materialCount")}
            for row in _course_rows(session, current_user.id)
        ],
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


# --------------------------------------------------------------------------
# User activity: logins, active time, tokens and turns, per user and in total.
# --------------------------------------------------------------------------

@dataclass
class Sitting:
    """One login and the turns made on the token it issued."""

    login_at: datetime
    last_at: datetime
    turns: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def minutes(self) -> float:
        return (self.last_at - self.login_at).total_seconds() / 60


def _as_utc(value: datetime) -> datetime:
    # SQLite hands back naive timestamps; Postgres hands back aware ones.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _sittings(
    logins: list[datetime],
    turns: list[tuple[datetime, int, int]],
    token_lifetime: timedelta,
) -> list[Sitting]:
    """Group a student's turns under the login whose token they were made on.

    A turn belongs to the latest login before it, as long as that login's token
    was still valid (there is no refresh: an expired token means a new login and
    a new event). Every metric on the page is read off these sittings -- logins,
    turns, tokens and active time (login to the last turn) -- so they cannot
    disagree with each other. A turn with no login to hang on (one logged before
    login events existed) is not usage this page can place and is left out.
    """
    # ponytail: active time is login-to-last-turn, no idle detection inside the
    # token's hour; add a client heartbeat if idle time ever matters.
    sittings = [Sitting(login_at=at, last_at=at) for at in sorted(logins)]
    index = 0
    for created_at, prompt, completion in sorted(turns):
        while index + 1 < len(sittings) and sittings[index + 1].login_at <= created_at:
            index += 1
        if not sittings:
            break
        sitting = sittings[index]
        if created_at < sitting.login_at or created_at - sitting.login_at > token_lifetime:
            continue
        sitting.turns += 1
        sitting.prompt_tokens += prompt
        sitting.completion_tokens += completion
        sitting.last_at = max(sitting.last_at, created_at)
    return sittings


@router.get("/activity")
def activity_statistics(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    _current_user: Annotated[User, Depends(require_role(UserRole.admin))],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, object]:
    """Per-student and total usage over the last ``days`` days, for the admin usage page.

    Professors and administrators never talk to the agent, so only students count.
    """

    since = datetime.now(timezone.utc) - timedelta(days=days)
    token_lifetime = timedelta(seconds=settings.jwt_expires_in)
    users = {
        user.id: user
        for user in session.scalars(select(User).where(User.role == UserRole.student))
    }

    logins: dict[str, list[datetime]] = defaultdict(list)
    for user_id, created_at in session.execute(
        select(LoginEvent.user_id, LoginEvent.created_at).where(LoginEvent.created_at >= since)
    ):
        logins[user_id].append(_as_utc(created_at))

    turns: dict[str, list[tuple[datetime, int, int]]] = defaultdict(list)
    for user_id, created_at, prompt, completion in session.execute(
        select(
            ChatLog.user_id, ChatLog.created_at, ChatLog.prompt_tokens, ChatLog.completion_tokens
        ).where(ChatLog.created_at >= since)
    ):
        turns[user_id].append((_as_utc(created_at), prompt or 0, completion or 0))

    by_date: dict[str, dict[str, float]] = defaultdict(
        lambda: {"logins": 0, "turns": 0, "tokens": 0, "activeMinutes": 0.0}
    )
    rows: list[dict[str, object]] = []
    for user_id, user in users.items():
        sittings = _sittings(logins.get(user_id, []), turns.get(user_id, []), token_lifetime)
        prompt_tokens = sum(sitting.prompt_tokens for sitting in sittings)
        completion_tokens = sum(sitting.completion_tokens for sitting in sittings)
        rows.append(
            {
                "userId": user_id,
                "name": user.name,
                "email": user.email,
                "loginCount": len(sittings),
                "lastLoginAt": sittings[-1].login_at if sittings else None,
                "activeMinutes": round(sum(sitting.minutes for sitting in sittings), 1),
                "turnCount": sum(sitting.turns for sitting in sittings),
                "promptTokens": prompt_tokens,
                "completionTokens": completion_tokens,
                "totalTokens": prompt_tokens + completion_tokens,
            }
        )
        # Everything a sitting did is booked on the day it was logged in.
        for sitting in sittings:
            day = by_date[sitting.login_at.date().isoformat()]
            day["logins"] += 1
            day["turns"] += sitting.turns
            day["tokens"] += sitting.prompt_tokens + sitting.completion_tokens
            day["activeMinutes"] += sitting.minutes

    rows.sort(key=lambda row: (-int(row["turnCount"]), -int(row["loginCount"]), str(row["name"])))
    return {
        "days": days,
        "since": since,
        "totals": {
            "userCount": len(users),
            "activeUserCount": sum(1 for row in rows if row["loginCount"]),
            "loginCount": sum(int(row["loginCount"]) for row in rows),
            "activeMinutes": round(sum(float(row["activeMinutes"]) for row in rows), 1),
            "turnCount": sum(int(row["turnCount"]) for row in rows),
            "promptTokens": sum(int(row["promptTokens"]) for row in rows),
            "completionTokens": sum(int(row["completionTokens"]) for row in rows),
            "totalTokens": sum(int(row["totalTokens"]) for row in rows),
        },
        "byDate": [
            {"date": day, **{key: round(value, 1) for key, value in values.items()}}
            for day, values in sorted(by_date.items())
        ],
        "users": rows,
    }


@router.get("/courses/{course_id}/keywords", response_model=CourseKeywordCounts)
def course_keywords(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(require_role([UserRole.admin, UserRole.professor]))],
) -> CourseKeywordCounts:
    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    if not can_manage_course(current_user, course):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return course_keyword_counts(
        session,
        course.id,
        tuple(settings.course_keyword_terms.get(course.id, DEFAULT_TERMS)),
        settings.keyword_minimum_students,
    )
