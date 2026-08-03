from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        from_attributes=True,
        populate_by_name=True,
    )


UserRole = Literal["student", "professor", "admin"]
CourseAgentStatus = Literal["draft", "active", "disabled"]
CourseMaterialStatus = Literal["pending", "processing", "completed", "failed"]


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


class AdminCourseCreate(CamelModel):
    name: str = Field(min_length=1, max_length=255)
    semester: str = Field(min_length=1, max_length=40)
    description: Optional[str] = None
    professor_id: str
    is_active: bool = True


class AdminCourseUpdate(CamelModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    semester: Optional[str] = Field(default=None, min_length=1, max_length=40)
    description: Optional[str] = None
    professor_id: Optional[str] = None
    is_active: Optional[bool] = None


class CourseRead(CamelModel):
    id: str
    code: str
    title: str
    term: str
    instructor_id: str
    instructor_name: str
    agent_status: CourseAgentStatus
    created_at: datetime
    updated_at: datetime


class AdminCourseRead(CamelModel):
    id: str
    name: str
    semester: str
    description: Optional[str] = None
    professor_id: str
    professor_name: str
    is_active: bool
    student_access_count: int
    created_at: datetime
    updated_at: datetime


class AdminCourseAccessRead(CamelModel):
    id: str
    course_id: str
    user_id: str
    user_name: str
    user_email: EmailStr
    access_role: str
    created_at: datetime


class CourseMaterialRead(CamelModel):
    id: str
    course_id: str
    uploaded_by: str
    original_file_name: str
    file_type: str
    file_size: int
    week: int
    processing_status: CourseMaterialStatus
    processing_error: Optional[str] = None
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime


class DocumentChunkRead(CamelModel):
    id: str
    material_id: str
    course_id: str
    chunk_index: int
    chunk_text: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    char_count: int
    embedding: Optional[list[float]] = None
    embedding_model: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class MaterialProcessingStatusRead(CamelModel):
    material_id: str
    processing_status: CourseMaterialStatus
    processing_error: Optional[str] = None
    chunk_count: int
    updated_at: datetime


NonBlankQuestion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RAGSearchRequest(BaseModel):
    course_id: str = Field(min_length=1)
    question: NonBlankQuestion
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    debug: bool = False


class RAGSearchResult(BaseModel):
    chunk_id: str
    material_id: str
    document_name: str
    page_number: Optional[int] = None
    chunk_index: int
    chunk_text: str
    score: float


class RAGSearchDebug(BaseModel):
    embedding_model: Optional[str] = None
    search_mode: str
    score_threshold: Optional[float] = None
    total_candidate_chunks: int


class RAGSearchResponse(BaseModel):
    course_id: str
    question: str
    top_k: int
    results: list[RAGSearchResult]
    debug: Optional[RAGSearchDebug] = None


class RAGStatusResponse(BaseModel):
    course_id: str
    material_count: int
    completed_material_count: int
    failed_material_count: int
    chunk_count: int
    embedded_chunk_count: int
    is_search_ready: bool


class Citation(CamelModel):
    material_id: str
    chunk_id: str
    title: str
    page: Optional[int] = None
    score: Optional[float] = None
    snippet: Optional[str] = None


class ChatSessionCreate(CamelModel):
    course_id: str


class ChatSessionRead(CamelModel):
    id: str
    user_id: str
    course_id: str
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ChatLogRead(CamelModel):
    id: str
    session_id: str
    user_id: str
    course_id: str
    question: str
    answer: str
    referenced_documents: list[dict[str, object]] = Field(default_factory=list)
    model_name: str
    response_time_ms: int
    is_grounded: bool
    safety_result: dict[str, object] = Field(default_factory=dict)
    retrieval_result: dict[str, object] = Field(default_factory=dict)
    created_at: datetime


class ChatSessionDetailRead(ChatSessionRead):
    logs: list[ChatLogRead] = Field(default_factory=list)


class ChatRequest(CamelModel):
    user_id: str
    course_id: str
    question: str = Field(min_length=1)


class ChatResponse(CamelModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    latency_ms: Optional[int] = None
