from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
<<<<<<< HEAD
    Integer,
=======
    JSON,
>>>>>>> refs/remotes/origin/main
    String,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class UserRole(str, Enum):
    student = "student"
    professor = "professor"
    admin = "admin"


class CourseMaterialStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ChatAnswerSourceType(str, Enum):
    """How a stored answer was produced, used by log screens and statistics."""

    rag = "rag"
    general_llm = "general_llm"
    safety_response = "safety_response"
    no_material = "no_material"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "password_hash IS NOT NULL OR external_auth_id IS NOT NULL",
            name="ck_users_auth_identity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    external_auth_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=True,
    )
    school_id: Mapped[Optional[str]] = mapped_column(
        String(80),
        unique=True,
        index=True,
        nullable=True,
    )
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(
            UserRole,
            name="user_role",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    courses: Mapped[list[Course]] = relationship(back_populates="professor")
    course_accesses: Mapped[list[CourseAccess]] = relationship(
        back_populates="user",
        passive_deletes=True,
    )
    uploaded_materials: Mapped[list[CourseMaterial]] = relationship(
        back_populates="uploader",
        foreign_keys="CourseMaterial.uploaded_by",
    )
    chat_sessions: Mapped[list[ChatSession]] = relationship(
        back_populates="user",
        passive_deletes=True,
    )
    chat_logs: Mapped[list[ChatLog]] = relationship(
        back_populates="user",
        passive_deletes=True,
    )


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    semester: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    professor_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    professor: Mapped[User] = relationship(back_populates="courses")
    access_entries: Mapped[list[CourseAccess]] = relationship(
        back_populates="course",
        passive_deletes=True,
    )
    materials: Mapped[list[CourseMaterial]] = relationship(
        back_populates="course",
        passive_deletes=True,
    )
    document_chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="course",
        passive_deletes=True,
    )
    chat_sessions: Mapped[list[ChatSession]] = relationship(
        back_populates="course",
        passive_deletes=True,
    )
    chat_logs: Mapped[list[ChatLog]] = relationship(
        back_populates="course",
        passive_deletes=True,
    )


class CourseAccess(Base):
    __tablename__ = "course_access"
    __table_args__ = (
        UniqueConstraint("course_id", "user_id", name="uq_course_access_course_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    access_role: Mapped[str] = mapped_column(
        String(40),
        default="student",
        server_default="student",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    course: Mapped[Course] = relationship(back_populates="access_entries")
    user: Mapped[User] = relationship(back_populates="course_accesses")


class CourseMaterial(Base):
    __tablename__ = "course_materials"
    __table_args__ = (
        CheckConstraint(
            "file_size >= 0",
            name="ck_course_materials_file_size_non_negative",
        ),
        CheckConstraint(
            "week >= 1 AND week <= 16",
            name="ck_course_materials_week_range",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    uploaded_by: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(40), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    week: Mapped[int] = mapped_column(
        SmallInteger,
        default=1,
        server_default="1",
        nullable=False,
    )
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    processing_status: Mapped[CourseMaterialStatus] = mapped_column(
        SQLEnum(
            CourseMaterialStatus,
            name="course_material_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=CourseMaterialStatus.pending,
        server_default=CourseMaterialStatus.pending.value,
        nullable=False,
    )
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    course: Mapped[Course] = relationship(back_populates="materials")
    uploader: Mapped[User] = relationship(
        back_populates="uploaded_materials",
        foreign_keys=[uploaded_by],
    )
<<<<<<< HEAD
    chunks: Mapped[list[DocumentChunk]] = relationship(
=======
    document_chunks: Mapped[list[DocumentChunk]] = relationship(
>>>>>>> refs/remotes/origin/main
        back_populates="material",
        passive_deletes=True,
    )


class DocumentChunk(Base):
<<<<<<< HEAD
    """A retrievable slice of a processed course material."""

=======
>>>>>>> refs/remotes/origin/main
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "material_id",
            "chunk_index",
<<<<<<< HEAD
            name="uq_document_chunks_material_chunk_index",
        ),
        CheckConstraint("char_count >= 0", name="ck_document_chunks_char_count_non_negative"),
=======
            name="uq_document_chunks_material_index",
        ),
        CheckConstraint(
            "char_count >= 0",
            name="ck_document_chunks_char_count_non_negative",
        ),
>>>>>>> refs/remotes/origin/main
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    material_id: Mapped[str] = mapped_column(
        ForeignKey("course_materials.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
<<<<<<< HEAD
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    section_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[Optional[list[float]]] = mapped_column(JSON, nullable=True)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    embedded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
=======
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[Optional[int]] = mapped_column(nullable=True)
    section_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    char_count: Mapped[int] = mapped_column(nullable=False)
    embedding: Mapped[Optional[list[float]]] = mapped_column(
        JSON(none_as_null=True),
        nullable=True,
    )
    embedding_model: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
>>>>>>> refs/remotes/origin/main
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

<<<<<<< HEAD
    material: Mapped[CourseMaterial] = relationship(back_populates="chunks")


class ChatSession(Base):
    """A course-scoped conversation owned by a single user."""

=======
    course: Mapped[Course] = relationship(back_populates="document_chunks")
    material: Mapped[CourseMaterial] = relationship(back_populates="document_chunks")


class ChatSession(Base):
>>>>>>> refs/remotes/origin/main
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

<<<<<<< HEAD
    user: Mapped[User] = relationship()
    course: Mapped[Course] = relationship()
    logs: Mapped[list[ChatLog]] = relationship(
        back_populates="session",
        passive_deletes=True,
=======
    user: Mapped[User] = relationship(back_populates="chat_sessions")
    course: Mapped[Course] = relationship(back_populates="chat_sessions")
    logs: Mapped[list[ChatLog]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
>>>>>>> refs/remotes/origin/main
        order_by="ChatLog.created_at",
    )


class ChatLog(Base):
<<<<<<< HEAD
    """One question/answer exchange kept for history, log review and statistics."""

    __tablename__ = "chat_logs"
=======
    __tablename__ = "chat_logs"
    __table_args__ = (
        CheckConstraint(
            "response_time_ms >= 0",
            name="ck_chat_logs_response_time_non_negative",
        ),
    )
>>>>>>> refs/remotes/origin/main

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
<<<<<<< HEAD
    referenced_documents: Mapped[list[dict]] = mapped_column(
=======
    referenced_documents: Mapped[list[dict[str, object]]] = mapped_column(
>>>>>>> refs/remotes/origin/main
        JSON,
        default=list,
        nullable=False,
    )
<<<<<<< HEAD
    model_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    response_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_grounded: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    answer_source_type: Mapped[ChatAnswerSourceType] = mapped_column(
        SQLEnum(
            ChatAnswerSourceType,
            name="chat_answer_source_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ChatAnswerSourceType.rag,
        server_default=ChatAnswerSourceType.rag.value,
        nullable=False,
    )
    safety_result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    retrieval_result: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
=======
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    response_time_ms: Mapped[int] = mapped_column(nullable=False)
    is_grounded: Mapped[bool] = mapped_column(Boolean, nullable=False)
    safety_result: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    retrieval_result: Mapped[dict[str, object]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
>>>>>>> refs/remotes/origin/main
        nullable=False,
    )

    session: Mapped[ChatSession] = relationship(back_populates="logs")
<<<<<<< HEAD
    user: Mapped[User] = relationship()
    course: Mapped[Course] = relationship()
=======
    user: Mapped[User] = relationship(back_populates="chat_logs")
    course: Mapped[Course] = relationship(back_populates="chat_logs")
>>>>>>> refs/remotes/origin/main
