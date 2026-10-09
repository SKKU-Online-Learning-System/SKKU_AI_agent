"""Role-scoped MVP usage statistics."""

from __future__ import annotations

import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated, Callable, Iterable

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.api.routes.chat_logs import mask_email
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
from app.services import weak_concept_stats
from app.services.rbac_service import can_manage_course
from app.services.voice.moss_memory import local_memory_path, read_local_memories

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


# --------------------------------------------------------------------------
# Weak concepts the course agent captured, seen from the teaching side.
# --------------------------------------------------------------------------


def _is_admin(user: User) -> bool:
    return str(getattr(user.role, "value", user.role)) == UserRole.admin.value


def _weak_concept_memories(settings: Settings) -> list[dict]:
    return read_local_memories(local_memory_path(settings))


def _student_labeler(
    session: Session, memories: list[dict], *, reveal_identity: bool
) -> Callable[[str], str]:
    """Name students the way chat logs do: full identity for admins, masked for professors."""
    ids = {str(memory.get("student_id")) for memory in memories if memory.get("student_id")}
    users = (
        {user.id: user for user in session.scalars(select(User).where(User.id.in_(ids)))}
        if ids
        else {}
    )

    def label(student_id: str) -> str:
        user = users.get(student_id)
        if user is None:
            return "삭제된 사용자"
        if reveal_identity:
            return f"{user.name} ({user.email})"
        return mask_email(user.email)

    return label


def _weak_concept_overview(settings: Settings, courses: Iterable[Course]) -> dict[str, object]:
    now = time.time()
    memories = _weak_concept_memories(settings)
    rows: list[dict] = []
    matched: dict[str, dict] = {}
    for course in courses:
        course_memories = weak_concept_stats.course_memories(memories, course.name)
        matched.update({str(memory.get("id")): memory for memory in course_memories})
        rows.append(
            {
                "courseId": course.id,
                "courseName": course.name,
                **weak_concept_stats.summarize_course(course_memories, now=now),
            }
        )
    return {
        "totals": weak_concept_stats.summarize_totals(rows, list(matched.values()), now=now),
        "courses": rows,
    }


@router.get("/weak-concepts")
def weak_concept_statistics(
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(require_role([UserRole.admin, UserRole.professor]))],
) -> dict[str, object]:
    """Return weak-concept totals per course: every course for admins, assigned ones for professors."""

    statement = select(Course).order_by(Course.name)
    if not _is_admin(current_user):
        statement = statement.where(Course.professor_id == current_user.id)
    return _weak_concept_overview(settings, session.scalars(statement))


@router.get("/weak-concepts/courses/{course_id}")
def course_weak_concept_statistics(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(require_role([UserRole.admin, UserRole.professor]))],
) -> dict[str, object]:
    """Return one course's weak concepts by concept, topic and student, plus recent captures."""

    course = session.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found")
    if not can_manage_course(current_user, course):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    memories = weak_concept_stats.course_memories(_weak_concept_memories(settings), course.name)
    label_for = _student_labeler(session, memories, reveal_identity=_is_admin(current_user))
    return {
        "courseId": course.id,
        "courseName": course.name,
        **weak_concept_stats.course_detail(memories, label_for=label_for, now=time.time()),
    }
