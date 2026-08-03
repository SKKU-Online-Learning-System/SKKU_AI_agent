from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import authorize_course_access, get_current_user
from app.db.session import get_db
from app.models import ChatSession, User
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ChatSessionCreate,
    ChatSessionDetailRead,
    ChatSessionRead,
)
from app.services.rag_service import RAGService

router = APIRouter(tags=["chat"])


@router.post(
    "/chat/sessions",
    response_model=ChatSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_session(
    payload: ChatSessionCreate,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatSessionRead:
    authorize_course_access(session, current_user, payload.course_id)
    chat_session = ChatSession(
        user_id=current_user.id,
        course_id=payload.course_id,
        title=None,
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


@router.post("/chat/sessions/{session_id}/messages", response_model=ChatResponse)
async def send_chat_message(
    session_id: str,
    payload: ChatRequest,
    session: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatResponse:
    _ = session_id
    authorize_course_access(session, current_user, payload.course_id)
    service = RAGService()
    return await service.answer(course_id=payload.course_id, question=payload.question)
