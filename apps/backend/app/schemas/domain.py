from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional

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
ChatSessionStatus = Literal["open", "archived"]


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
    title: Optional[str] = None
    # Kept for backwards compatibility; the owner always comes from the access token.
    user_id: Optional[str] = None


class ChatSessionRead(CamelModel):
    id: str
    user_id: str
    course_id: str
    title: Optional[str] = None
    status: ChatSessionStatus = "open"
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


class ChatRequest(CamelModel):
    course_id: str
    question: str = Field(min_length=1)
    user_id: Optional[str] = None


class ChatResponse(CamelModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    latency_ms: Optional[int] = None


# --- Document processing and retrieval -------------------------------------


class MaterialProcessingStatusRead(CamelModel):
    material_id: str
    processing_status: CourseMaterialStatus
    processing_error: Optional[str] = None
    chunk_count: int
    embedding_model: Optional[str] = None
    updated_at: datetime


class CourseRagStatusRead(CamelModel):
    course_id: str
    material_count: int
    completed_material_count: int
    failed_material_count: int
    pending_material_count: int
    chunk_count: int
    embedded_chunk_count: int
    is_search_ready: bool


class RagSearchRequest(CamelModel):
    course_id: str
    question: str = Field(min_length=1, max_length=2000)
    top_k: Optional[int] = Field(default=None, ge=1, le=100)
    debug: bool = False


class RagSearchResultRead(CamelModel):
    chunk_id: str
    material_id: str
    document_name: str
    page_number: Optional[int] = None
    chunk_index: int
    chunk_text: str
    score: float


class RagSearchDebugRead(CamelModel):
    embedding_model: str
    search_mode: str
    score_threshold: float
    total_candidate_chunks: int


class RagSearchResponse(CamelModel):
    course_id: str
    question: str
    top_k: int
    results: list[RagSearchResultRead] = Field(default_factory=list)
    debug: Optional[RagSearchDebugRead] = None


# --- Answer generation ------------------------------------------------------


AnswerSourceType = Literal["rag", "general_llm", "safety_response", "no_material"]
SafetyCategory = Literal[
    "normal",
    "assignment_direct_answer",
    "exam_direct_answer",
    "privacy_request",
    "prompt_injection",
    "unsafe_content",
]


class AnswerSourceRead(CamelModel):
    material_id: str
    document_name: str
    page_number: Optional[int] = None
    chunk_index: int
    score: float


class RetrievalSummaryRead(CamelModel):
    result_count: int
    max_score: Optional[float] = None
    score_threshold: float
    reason: Optional[str] = None


class SafetyResultRead(CamelModel):
    blocked: bool
    category: SafetyCategory
    reason: Optional[str] = None
    redirect_type: Optional[str] = None


class ChatAskRequest(CamelModel):
    course_id: str
    question: str = Field(min_length=1)
    chat_session_id: Optional[str] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=100)


class ChatAnswerResponse(CamelModel):
    session_id: str
    log_id: str
    answer: str
    sources: list[AnswerSourceRead] = Field(default_factory=list)
    is_grounded: bool
    answer_source_type: AnswerSourceType
    model_name: Optional[str] = None
    response_time_ms: Optional[int] = None
    retrieval_summary: RetrievalSummaryRead
    safety: SafetyResultRead


class ChatSessionSummaryRead(CamelModel):
    id: str
    course_id: str
    course_name: str
    title: Optional[str] = None
    message_count: int
    last_message_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ChatHistoryLogRead(CamelModel):
    id: str
    question: str
    answer: str
    sources: list[AnswerSourceRead] = Field(default_factory=list)
    referenced_documents: list[dict[str, object]] = Field(default_factory=list)
    is_grounded: bool
    answer_source_type: AnswerSourceType
    created_at: datetime


class ChatSessionDetailRead(CamelModel):
    session: ChatSessionSummaryRead
    logs: list[ChatHistoryLogRead] = Field(default_factory=list)


class ChatSessionTitleUpdate(CamelModel):
    title: str = Field(min_length=1, max_length=255)


# --- Log review -------------------------------------------------------------


class ChatLogListItemRead(CamelModel):
    id: str
    course_id: str
    course_name: str
    user_label: str
    user_id: Optional[str] = None
    question: str
    answer_preview: str
    is_grounded: bool
    answer_source_type: AnswerSourceType
    safety_category: SafetyCategory
    created_at: datetime


class ChatLogDetailRead(CamelModel):
    id: str
    course_id: str
    course_name: str
    user_label: str
    user_id: Optional[str] = None
    question: str
    answer: str
    referenced_documents: list[AnswerSourceRead] = Field(default_factory=list)
    retrieval_result: dict[str, Any] = Field(default_factory=dict)
    safety_result: dict[str, Any] = Field(default_factory=dict)
    is_grounded: bool
    answer_source_type: AnswerSourceType
    model_name: Optional[str] = None
    response_time_ms: Optional[int] = None
    created_at: datetime


class ChatLogListResponse(CamelModel):
    logs: list[ChatLogListItemRead] = Field(default_factory=list)
    total: int
