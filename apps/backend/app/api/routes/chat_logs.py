"""Question history is available only to the account that created it."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import authorize_course_access, require_role
from app.db.session import get_db
from app.models import ChatLog, Course, User
from app.schemas import ChatLogListItemRead, ChatLogListResponse

router = APIRouter(tags=["chat-logs"])

ANSWER_PREVIEW_LENGTH = 120


@router.get("/student/chat-logs", response_model=ChatLogListResponse)
async def list_own_chat_logs(
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role("student"))],
    course_id: Annotated[Optional[str], Query()] = None,
    keyword: Annotated[Optional[str], Query()] = None,
    is_grounded: Annotated[Optional[bool], Query()] = None,
    safety_category: Annotated[Optional[str], Query()] = None,
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
    if is_grounded is not None:
        statement = statement.where(ChatLog.is_grounded == is_grounded)
    if safety_category:
        statement = statement.where(ChatLog.safety_result["category"].as_string() == safety_category)
    return _paginated_logs(
        session=session,
        statement=statement,
        user=current_user,
        keyword=keyword,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


def _paginated_logs(
    *,
    session: Session,
    statement: Select,
    user: User,
    keyword: Optional[str],
    from_date: Optional[datetime],
    to_date: Optional[datetime],
    limit: int,
    offset: int,
) -> ChatLogListResponse:
    statement = _apply_filters(
        statement,
        keyword=keyword,
        from_date=from_date,
        to_date=to_date,
    )
    total = session.scalar(
        select(func.count()).select_from(statement.subquery())
    )
    logs = session.scalars(
        statement.order_by(ChatLog.created_at.desc()).limit(limit).offset(offset)
    ).all()

    return ChatLogListResponse(
        logs=[_log_list_item(session, log, user) for log in logs],
        total=int(total or 0),
    )


def _apply_filters(
    statement: Select,
    *,
    keyword: Optional[str],
    from_date: Optional[datetime],
    to_date: Optional[datetime],
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
    return statement


def _course_name(session: Session, course_id: str) -> str:
    return session.scalar(select(Course.name).where(Course.id == course_id)) or "삭제된 과목"


def _log_list_item(session: Session, log: ChatLog, user: User) -> ChatLogListItemRead:
    answer = log.answer or ""
    preview = answer[:ANSWER_PREVIEW_LENGTH]
    if len(answer) > ANSWER_PREVIEW_LENGTH:
        preview = f"{preview}…"

    return ChatLogListItemRead(
        id=log.id,
        course_id=log.course_id,
        course_name=_course_name(session, log.course_id),
        user_label=f"{user.name} ({user.email})",
        user_id=user.id,
        question=log.question,
        answer_preview=preview,
        is_grounded=log.is_grounded,
        answer_source_type=getattr(log.answer_source_type, "value", log.answer_source_type),
        safety_category=(log.safety_result or {}).get("category", "normal"),
        created_at=log.created_at,
    )
