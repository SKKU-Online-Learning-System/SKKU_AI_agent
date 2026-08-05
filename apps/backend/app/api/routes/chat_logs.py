"""Question and answer log review for professors and admins.

Professors are limited to their own courses; admins see everything. Student
identity is reduced to a masked label unless an admin is reading.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, Text, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import authorize_course_access, require_role
from app.db.session import get_db
from app.models import ChatLog, Course, User, UserRole
from app.schemas import (
    AnswerSourceRead,
    ChatLogDetailRead,
    ChatLogListItemRead,
    ChatLogListResponse,
)
from app.services.rbac_service import can_manage_course

router = APIRouter(tags=["chat-logs"])

ANSWER_PREVIEW_LENGTH = 120


@router.get(
    "/professor/courses/{course_id}/chat-logs",
    response_model=ChatLogListResponse,
)
async def list_course_chat_logs(
    course_id: str,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["professor", "admin"]))],
    user_id: Annotated[Optional[str], Query()] = None,
    keyword: Annotated[Optional[str], Query()] = None,
    from_date: Annotated[Optional[datetime], Query(alias="from")] = None,
    to_date: Annotated[Optional[datetime], Query(alias="to")] = None,
    is_grounded: Annotated[Optional[bool], Query()] = None,
    safety_category: Annotated[Optional[str], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChatLogListResponse:
    course = authorize_course_access(session, current_user, course_id)
    _require_course_management(current_user, course)

    statement = select(ChatLog).where(ChatLog.course_id == course.id)
    if user_id:
        statement = statement.where(ChatLog.user_id == user_id)
    return _paginated_logs(
        session=session,
        statement=statement,
        reveal_identity=_is_admin(current_user),
        keyword=keyword,
        from_date=from_date,
        to_date=to_date,
        is_grounded=is_grounded,
        safety_category=safety_category,
        limit=limit,
        offset=offset,
    )


@router.get("/student/chat-logs", response_model=ChatLogListResponse)
async def list_own_chat_logs(
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role("student"))],
    course_id: Annotated[Optional[str], Query()] = None,
    keyword: Annotated[Optional[str], Query()] = None,
    from_date: Annotated[Optional[datetime], Query(alias="from")] = None,
    to_date: Annotated[Optional[datetime], Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChatLogListResponse:
    """List only the authenticated student's own question history."""

    statement = select(ChatLog).where(ChatLog.user_id == current_user.id)
    if course_id:
        authorize_course_access(session, current_user, course_id)
        statement = statement.where(ChatLog.course_id == course_id)
    return _paginated_logs(
        session=session,
        statement=statement,
        reveal_identity=True,
        keyword=keyword,
        from_date=from_date,
        to_date=to_date,
        is_grounded=None,
        safety_category=None,
        limit=limit,
        offset=offset,
    )


@router.get("/professor/chat-logs/{log_id}", response_model=ChatLogDetailRead)
async def read_course_chat_log(
    log_id: str,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role(["professor", "admin"]))],
) -> ChatLogDetailRead:
    log = _load_log(session, log_id)
    course = authorize_course_access(session, current_user, log.course_id)
    _require_course_management(current_user, course)
    return _log_detail(session, log, reveal_identity=_is_admin(current_user))


@router.get("/admin/chat-logs", response_model=ChatLogListResponse)
async def list_all_chat_logs(
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role("admin"))],
    course_id: Annotated[Optional[str], Query()] = None,
    user_id: Annotated[Optional[str], Query()] = None,
    keyword: Annotated[Optional[str], Query()] = None,
    from_date: Annotated[Optional[datetime], Query(alias="from")] = None,
    to_date: Annotated[Optional[datetime], Query(alias="to")] = None,
    is_grounded: Annotated[Optional[bool], Query()] = None,
    safety_category: Annotated[Optional[str], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ChatLogListResponse:
    _ = current_user
    statement = select(ChatLog)
    if course_id:
        statement = statement.where(ChatLog.course_id == course_id)
    if user_id:
        statement = statement.where(ChatLog.user_id == user_id)

    return _paginated_logs(
        session=session,
        statement=statement,
        reveal_identity=True,
        keyword=keyword,
        from_date=from_date,
        to_date=to_date,
        is_grounded=is_grounded,
        safety_category=safety_category,
        limit=limit,
        offset=offset,
    )


@router.get("/admin/chat-logs/{log_id}", response_model=ChatLogDetailRead)
async def read_any_chat_log(
    log_id: str,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role("admin"))],
) -> ChatLogDetailRead:
    _ = current_user
    return _log_detail(session, _load_log(session, log_id), reveal_identity=True)


def _is_admin(user: User) -> bool:
    return getattr(user.role, "value", user.role) == UserRole.admin.value


def _require_course_management(user: User, course: Course) -> None:
    if not can_manage_course(user, course):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="담당 과목의 로그만 조회할 수 있습니다.",
        )


def _load_log(session: Session, log_id: str) -> ChatLog:
    log = session.get(ChatLog, log_id)
    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="로그를 찾을 수 없습니다.")

    return log


def _paginated_logs(
    *,
    session: Session,
    statement: Select,
    reveal_identity: bool,
    keyword: Optional[str],
    from_date: Optional[datetime],
    to_date: Optional[datetime],
    is_grounded: Optional[bool],
    safety_category: Optional[str],
    limit: int,
    offset: int,
) -> ChatLogListResponse:
    statement = _apply_filters(
        statement,
        keyword=keyword,
        from_date=from_date,
        to_date=to_date,
        is_grounded=is_grounded,
        safety_category=safety_category,
    )
    total = session.scalar(
        select(func.count()).select_from(statement.subquery())
    )
    logs = session.scalars(
        statement.order_by(ChatLog.created_at.desc()).limit(limit).offset(offset)
    ).all()

    return ChatLogListResponse(
        logs=[_log_list_item(session, log, reveal_identity) for log in logs],
        total=int(total or 0),
    )


def _apply_filters(
    statement: Select,
    *,
    keyword: Optional[str],
    from_date: Optional[datetime],
    to_date: Optional[datetime],
    is_grounded: Optional[bool],
    safety_category: Optional[str],
) -> Select:
    if keyword:
        pattern = f"%{keyword}%"
        statement = statement.where(
            or_(ChatLog.question.ilike(pattern), ChatLog.answer.ilike(pattern))
        )
    if from_date:
        statement = statement.where(ChatLog.created_at >= from_date)
    if to_date:
        statement = statement.where(ChatLog.created_at <= to_date)
    if is_grounded is not None:
        statement = statement.where(ChatLog.is_grounded.is_(is_grounded))
    if safety_category:
        # safety_result is stored as JSON, so filter on the rendered text.
        statement = statement.where(
            func.cast(ChatLog.safety_result, Text).ilike(f'%"category": "{safety_category}"%')
        )

    return statement


def _user_label(session: Session, log: ChatLog, reveal_identity: bool) -> str:
    user = session.get(User, log.user_id)
    if user is None:
        return "삭제된 사용자"
    if reveal_identity:
        return f"{user.name} ({user.email})"

    return mask_email(user.email)


def mask_email(email: str) -> str:
    """Keep just enough of the address to tell users apart in a log list."""

    local, _, domain = email.partition("@")
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}***@{domain}" if domain else f"{visible}***"


def _course_name(session: Session, course_id: str) -> str:
    return session.scalar(select(Course.name).where(Course.id == course_id)) or "삭제된 과목"


def _log_list_item(session: Session, log: ChatLog, reveal_identity: bool) -> ChatLogListItemRead:
    answer = log.answer or ""
    preview = answer[:ANSWER_PREVIEW_LENGTH]
    if len(answer) > ANSWER_PREVIEW_LENGTH:
        preview = f"{preview}…"

    return ChatLogListItemRead(
        id=log.id,
        course_id=log.course_id,
        course_name=_course_name(session, log.course_id),
        user_label=_user_label(session, log, reveal_identity),
        user_id=log.user_id if reveal_identity else None,
        question=log.question,
        answer_preview=preview,
        is_grounded=log.is_grounded,
        answer_source_type=getattr(log.answer_source_type, "value", log.answer_source_type),
        safety_category=(log.safety_result or {}).get("category", "normal"),
        created_at=log.created_at,
    )


def _log_detail(session: Session, log: ChatLog, reveal_identity: bool) -> ChatLogDetailRead:
    return ChatLogDetailRead(
        id=log.id,
        course_id=log.course_id,
        course_name=_course_name(session, log.course_id),
        user_label=_user_label(session, log, reveal_identity),
        user_id=log.user_id if reveal_identity else None,
        question=log.question,
        answer=log.answer,
        referenced_documents=[
            AnswerSourceRead.model_validate(source) for source in (log.referenced_documents or [])
        ],
        retrieval_result=log.retrieval_result or {},
        safety_result=log.safety_result or {},
        is_grounded=log.is_grounded,
        answer_source_type=getattr(log.answer_source_type, "value", log.answer_source_type),
        model_name=log.model_name,
        response_time_ms=log.response_time_ms,
        created_at=log.created_at,
    )
