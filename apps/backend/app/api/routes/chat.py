from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, status

from app.schemas import ChatRequest, ChatResponse, ChatSessionCreate, ChatSessionRead
from app.services.rag_service import RAGService

router = APIRouter(tags=["chat"])


@router.post(
    "/chat/sessions",
    response_model=ChatSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_session(payload: ChatSessionCreate) -> ChatSessionRead:
    now = datetime.now(timezone.utc)
    return ChatSessionRead(
        id=str(uuid4()),
        user_id=payload.user_id,
        course_id=payload.course_id,
        title=payload.title,
        status="open",
        created_at=now,
        updated_at=now,
    )


@router.post("/chat/sessions/{session_id}/messages", response_model=ChatResponse)
async def send_chat_message(session_id: str, payload: ChatRequest) -> ChatResponse:
    _ = session_id
    service = RAGService()
    return await service.answer(course_id=payload.course_id, question=payload.question)
