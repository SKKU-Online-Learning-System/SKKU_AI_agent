from datetime import datetime, timezone
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import authorize_course_access, get_current_user
from app.db.session import get_db
from app.models import User
from app.schemas import ChatRequest, ChatResponse, ChatSessionCreate, ChatSessionRead
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
    now = datetime.now(timezone.utc)
    return ChatSessionRead(
        id=str(uuid4()),
        user_id=current_user.id,
        course_id=payload.course_id,
        title=payload.title,
        status="open",
        created_at=now,
        updated_at=now,
    )


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
