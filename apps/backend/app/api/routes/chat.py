<<<<<<< HEAD
"""Chatbot endpoints: ask a question, and read your own conversation history."""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
=======
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
>>>>>>> refs/remotes/origin/main
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.deps import authorize_course_access, get_current_user, require_role
from app.core.config import Settings, get_settings
from app.db.session import get_db
<<<<<<< HEAD
from app.models import ChatLog, ChatSession, Course, User
from app.schemas import (
    AnswerSourceRead,
    ChatAnswerResponse,
    ChatAskRequest,
    ChatHistoryLogRead,
    ChatSessionCreate,
    ChatSessionDetailRead,
    ChatSessionRead,
    ChatSessionSummaryRead,
    ChatSessionTitleUpdate,
    RetrievalSummaryRead,
    SafetyResultRead,
)
from app.services.chat_service import (
    AnswerGenerationError,
    ChatService,
    ChatSessionAccessError,
    ChatSessionNotFoundError,
    ChatValidationError,
)
=======
from app.models import ChatSession, User
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ChatSessionCreate,
    ChatSessionDetailRead,
    ChatSessionRead,
)
from app.services.rag_service import RAGService
>>>>>>> refs/remotes/origin/main

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatAnswerResponse)
async def ask_course_agent(
    payload: ChatAskRequest,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatAnswerResponse:
    course = authorize_course_access(session, current_user, payload.course_id)
    service = ChatService(session, settings)

    try:
        # Retrieval and generation are blocking, so keep them off the event loop.
        answer = await run_in_threadpool(
            service.answer_question,
            user=current_user,
            course=course,
            question=payload.question,
            chat_session_id=payload.chat_session_id,
            top_k=payload.top_k,
        )
    except ChatValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ChatSessionAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AnswerGenerationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{exc.code}: {exc}",
        ) from exc

    return ChatAnswerResponse(
        session_id=answer.session_id,
        log_id=answer.log_id,
        answer=answer.answer,
        sources=[
            AnswerSourceRead(
                material_id=source.material_id,
                document_name=source.document_name,
                page_number=source.page_number,
                chunk_index=source.chunk_index,
                score=source.score,
            )
            for source in answer.sources
        ],
        is_grounded=answer.is_grounded,
        answer_source_type=answer.answer_source_type,
        model_name=answer.model_name,
        response_time_ms=answer.response_time_ms,
        retrieval_summary=RetrievalSummaryRead(
            result_count=answer.summary.result_count,
            max_score=answer.summary.max_score,
            score_threshold=answer.summary.score_threshold,
            reason=answer.summary.reason,
        ),
        safety=SafetyResultRead(
            blocked=answer.safety.blocked,
            category=answer.safety.category,
            reason=answer.safety.reason,
            redirect_type=answer.safety.redirect_type,
        ),
    )


@router.post(
    "/chat/sessions",
    response_model=ChatSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_session(
    payload: ChatSessionCreate,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatSessionRead:
<<<<<<< HEAD
    course = authorize_course_access(session, current_user, payload.course_id)
    chat_session = ChatService(session, settings).create_session(
        current_user,
        course,
        payload.title,
    )
    return ChatSessionRead.model_validate(chat_session)


@router.get("/chat/sessions", response_model=list[ChatSessionSummaryRead])
async def list_my_chat_sessions(
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    course_id: Annotated[Optional[str], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ChatSessionSummaryRead]:
    return _list_sessions(session, current_user, course_id, limit, offset)


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionDetailRead)
async def read_my_chat_session(
    session_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatSessionDetailRead:
    return _read_session_detail(session, settings, current_user, session_id)


@router.patch("/chat/sessions/{session_id}", response_model=ChatSessionSummaryRead)
async def rename_my_chat_session(
    session_id: str,
    payload: ChatSessionTitleUpdate,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatSessionSummaryRead:
    chat_session = _load_owned_session(session, settings, current_user, session_id)
    chat_session.title = payload.title
    session.commit()
    session.refresh(chat_session)
    return _session_summary(session, chat_session)


@router.delete("/chat/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_chat_session(
    session_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    chat_session = _load_owned_session(session, settings, current_user, session_id)
    session.delete(chat_session)
    session.commit()


# Student-facing aliases keep the role-scoped paths used by the web app.


@router.get("/student/chat-sessions", response_model=list[ChatSessionSummaryRead])
async def list_student_chat_sessions(
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_role("student"))],
    course_id: Annotated[Optional[str], Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ChatSessionSummaryRead]:
    return _list_sessions(session, current_user, course_id, limit, offset)


@router.get("/student/chat-sessions/{session_id}", response_model=ChatSessionDetailRead)
async def read_student_chat_session(
    session_id: str,
    session: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    current_user: Annotated[User, Depends(require_role("student"))],
) -> ChatSessionDetailRead:
    return _read_session_detail(session, settings, current_user, session_id)


def _load_owned_session(
    session: Session,
    settings: Settings,
    current_user: User,
    session_id: str,
) -> ChatSession:
    try:
        return ChatService(session, settings).load_owned_session(current_user, session_id)
    except ChatSessionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ChatSessionAccessError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


def _read_session_detail(
    session: Session,
    settings: Settings,
    current_user: User,
    session_id: str,
) -> ChatSessionDetailRead:
    chat_session = _load_owned_session(session, settings, current_user, session_id)
    # Re-check course access so a revoked enrolment cannot keep reading a course.
    authorize_course_access(session, current_user, chat_session.course_id)

    logs = session.scalars(
        select(ChatLog)
        .where(ChatLog.session_id == chat_session.id)
        .order_by(ChatLog.created_at)
    ).all()

    return ChatSessionDetailRead(
        session=_session_summary(session, chat_session),
        logs=[
            ChatHistoryLogRead(
                id=log.id,
                question=log.question,
                answer=log.answer,
                sources=[
                    AnswerSourceRead.model_validate(source)
                    for source in (log.referenced_documents or [])
                ],
                is_grounded=log.is_grounded,
                answer_source_type=getattr(
                    log.answer_source_type,
                    "value",
                    log.answer_source_type,
                ),
                created_at=log.created_at,
            )
            for log in logs
        ],
=======
    authorize_course_access(session, current_user, payload.course_id)
    chat_session = ChatSession(
        user_id=current_user.id,
        course_id=payload.course_id,
        title=None,
>>>>>>> refs/remotes/origin/main
    )
    session.add(chat_session)
    session.commit()
    session.refresh(chat_session)
    return ChatSessionRead.model_validate(chat_session)


@router.get("/chat/sessions", response_model=list[ChatSessionRead])
def list_chat_sessions(
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[ChatSession]:
    return list(
        session.scalars(
            select(ChatSession)
            .where(ChatSession.user_id == current_user.id)
            .order_by(ChatSession.updated_at.desc(), ChatSession.id)
        ).all()
    )


def get_owned_chat_session(
    session: Session,
    current_user: User,
    session_id: str,
) -> ChatSession:
    chat_session = session.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
    )
    if chat_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found",
        )
    return chat_session


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionDetailRead)
def get_chat_session(
    session_id: str,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatSession:
    return get_owned_chat_session(session, current_user, session_id)


@router.delete(
    "/chat/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_chat_session(
    session_id: str,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    chat_session = get_owned_chat_session(session, current_user, session_id)
    session.delete(chat_session)
    session.commit()


def _list_sessions(
    session: Session,
    current_user: User,
    course_id: Optional[str],
    limit: int,
    offset: int,
) -> list[ChatSessionSummaryRead]:
    statement = (
        select(ChatSession)
        .where(ChatSession.user_id == current_user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if course_id:
        statement = statement.where(ChatSession.course_id == course_id)

    return [
        _session_summary(session, chat_session)
        for chat_session in session.scalars(statement).all()
    ]


def _session_summary(session: Session, chat_session: ChatSession) -> ChatSessionSummaryRead:
    course_name = session.scalar(select(Course.name).where(Course.id == chat_session.course_id))
    message_count, last_message_at = session.execute(
        select(func.count(ChatLog.id), func.max(ChatLog.created_at)).where(
            ChatLog.session_id == chat_session.id
        )
    ).one()

    return ChatSessionSummaryRead(
        id=chat_session.id,
        course_id=chat_session.course_id,
        course_name=course_name or "삭제된 과목",
        title=chat_session.title,
        message_count=int(message_count or 0),
        last_message_at=last_message_at,
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
    )
