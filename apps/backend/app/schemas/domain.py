from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        from_attributes=True,
        populate_by_name=True,
    )


UserRole = Literal["student", "instructor", "admin"]
CourseAgentStatus = Literal["draft", "active", "disabled"]
CourseMaterialStatus = Literal["uploaded", "processing", "ready", "failed"]
ChatSessionStatus = Literal["open", "archived"]
ChatMessageRole = Literal["user", "assistant", "system"]


class UserRead(CamelModel):
    id: str
    email: EmailStr
    name: str
    role: UserRole
    department: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class CourseCreate(CamelModel):
    code: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=255)
    term: str = Field(min_length=1, max_length=40)
    instructor_id: str
    agent_status: CourseAgentStatus = "draft"


class CourseRead(CamelModel):
    id: str
    code: str
    title: str
    term: str
    instructor_id: str
    agent_status: CourseAgentStatus
    created_at: datetime
    updated_at: datetime


class CourseMaterialRead(CamelModel):
    id: str
    course_id: str
    uploaded_by: str
    title: str
    file_name: str
    file_type: str
    storage_uri: str
    status: CourseMaterialStatus
    checksum: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class DocumentChunkRead(CamelModel):
    id: str
    material_id: str
    course_id: str
    chunk_index: int
    content: str
    embedding_model: Optional[str] = None
    token_count: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class Citation(CamelModel):
    material_id: str
    chunk_id: str
    title: str
    page: Optional[int] = None
    score: Optional[float] = None
    snippet: Optional[str] = None


class ChatSessionCreate(CamelModel):
    user_id: str
    course_id: str
    title: Optional[str] = None


class ChatSessionRead(CamelModel):
    id: str
    user_id: str
    course_id: str
    title: Optional[str] = None
    status: ChatSessionStatus
    created_at: datetime
    updated_at: datetime


class ChatLogRead(CamelModel):
    id: str
    session_id: str
    course_id: str
    user_id: str
    role: ChatMessageRole
    message: str
    citations: list[Citation] = Field(default_factory=list)
    latency_ms: Optional[int] = None
    created_at: datetime


class ChatRequest(CamelModel):
    user_id: str
    course_id: str
    question: str = Field(min_length=1)


class ChatResponse(CamelModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    latency_ms: Optional[int] = None
