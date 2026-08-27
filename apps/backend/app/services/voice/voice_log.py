"""Persist voice-agent turns into the shared chat log and session tables.

Voice answers must be auditable exactly like text chat answers, so they reuse
``ChatSession``/``ChatLog`` instead of a parallel store. Professors and admins
then see voice questions in the existing log screens for free.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChatAnswerSourceType, ChatLog, ChatSession, Course, User
from app.services.chat_service import build_session_title
from app.services.safety_service import SafetyResult
from app.services.voice.brain import MAX_HISTORY_MESSAGES, VoiceContext

logger = logging.getLogger(__name__)


def resolve_session(
    db: Session,
    user: User,
    course: Course,
    chat_session_id: Optional[str],
) -> ChatSession:
    """Return the learner's voice session, creating one on the first turn."""
    if chat_session_id:
        chat_session = db.get(ChatSession, chat_session_id)
        if (
            chat_session is not None
            and chat_session.user_id == user.id
            and chat_session.course_id == course.id
        ):
            return chat_session

    chat_session = ChatSession(user_id=user.id, course_id=course.id)
    db.add(chat_session)
    db.commit()
    db.refresh(chat_session)
    return chat_session


def restore_history(
    db: Session,
    context: VoiceContext,
    user: User,
    course: Course,
    chat_session_id: str,
) -> bool:
    """Reload a stored conversation into the in-memory voice session.

    A learner reopening a past conversation from 대화 이력 lands on a fresh
    process-local context, so the model would otherwise answer with no memory of
    what was already discussed.

    Returns:
        False when the session does not exist or belongs to another learner or
        course, so the caller can answer 404 instead of leaking anything.
    """
    chat_session = db.get(ChatSession, chat_session_id)
    if (
        chat_session is None
        or chat_session.user_id != user.id
        or chat_session.course_id != course.id
    ):
        return False

    logs = db.scalars(
        select(ChatLog)
        .where(ChatLog.session_id == chat_session.id)
        .order_by(ChatLog.created_at)
    ).all()

    history: list[dict] = []
    for log in logs:
        history.append({"role": "user", "content": log.question})
        history.append({"role": "assistant", "content": log.answer})

    context.history = history[-MAX_HISTORY_MESSAGES:]
    context.chat_session_id = chat_session.id
    context.last_material_sources = []
    return True


def log_turn(
    db: Session,
    *,
    chat_session: ChatSession,
    user: User,
    course: Course,
    question: str,
    answer: str,
    material_sources: Sequence[dict],
    web_sources: Sequence[str],
    tools_used: Sequence[str],
    mode: str,
    model_name: Optional[str],
    response_time_ms: int,
    safety: SafetyResult,
    provider_name: Optional[str] = None,
) -> str:
    """Write one voice turn to the chat log and return its id."""
    is_grounded = bool(material_sources)
    if safety.blocked:
        source_type = ChatAnswerSourceType.safety_response
    elif is_grounded:
        source_type = ChatAnswerSourceType.rag
    elif web_sources:
        source_type = ChatAnswerSourceType.general_llm
    else:
        source_type = ChatAnswerSourceType.no_material

    retrieval_result = {
        "channel": "voice",
        "mode": mode,
        "tools_used": list(tools_used),
        "web_sources": list(web_sources),
        "result_count": len(material_sources),
    }
    if provider_name:
        retrieval_result["provider"] = provider_name

    log = ChatLog(
        session_id=chat_session.id,
        user_id=user.id,
        course_id=course.id,
        question=question,
        answer=answer,
        referenced_documents=list(material_sources),
        model_name=model_name,
        response_time_ms=response_time_ms,
        is_grounded=is_grounded,
        answer_source_type=source_type,
        safety_result=safety.as_dict(),
        retrieval_result=retrieval_result,
    )
    db.add(log)

    if not chat_session.title:
        chat_session.title = build_session_title(question)
    chat_session.updated_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(log)
    return log.id
