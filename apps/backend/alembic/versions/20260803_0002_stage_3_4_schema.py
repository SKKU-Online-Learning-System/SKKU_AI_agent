"""Create the document chunk and chat log schema for stages 3 and 4.

Revision ID: 20260803_0002
Revises: 20260710_0001
Create Date: 2026-08-03
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260803_0002"
down_revision: Optional[str] = "20260710_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

chat_answer_source_type = sa.Enum(
    "rag",
    "general_llm",
    "safety_response",
    "no_material",
    name="chat_answer_source_type",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("material_id", sa.String(length=36), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(length=255), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("embedding", sa.JSON(), nullable=True),
        sa.Column("embedding_model", sa.String(length=120), nullable=True),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_count >= 0",
            name="ck_document_chunks_char_count_non_negative",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["course_materials.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "material_id",
            "chunk_index",
            name="uq_document_chunks_material_chunk_index",
        ),
    )
    op.create_index(
        "ix_document_chunks_course_id",
        "document_chunks",
        ["course_id"],
        unique=False,
    )
    op.create_index(
        "ix_document_chunks_material_id",
        "document_chunks",
        ["material_id"],
        unique=False,
    )

    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_sessions_course_id",
        "chat_sessions",
        ["course_id"],
        unique=False,
    )
    op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"], unique=False)

    op.create_table(
        "chat_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("referenced_documents", sa.JSON(), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("response_time_ms", sa.Integer(), nullable=True),
        sa.Column(
            "is_grounded",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "answer_source_type",
            chat_answer_source_type,
            server_default="rag",
            nullable=False,
        ),
        sa.Column("safety_result", sa.JSON(), nullable=False),
        sa.Column("retrieval_result", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_logs_course_id", "chat_logs", ["course_id"], unique=False)
    op.create_index("ix_chat_logs_created_at", "chat_logs", ["created_at"], unique=False)
    op.create_index("ix_chat_logs_session_id", "chat_logs", ["session_id"], unique=False)
    op.create_index("ix_chat_logs_user_id", "chat_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_chat_logs_user_id", table_name="chat_logs")
    op.drop_index("ix_chat_logs_session_id", table_name="chat_logs")
    op.drop_index("ix_chat_logs_created_at", table_name="chat_logs")
    op.drop_index("ix_chat_logs_course_id", table_name="chat_logs")
    op.drop_table("chat_logs")
    op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_course_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
    op.drop_index("ix_document_chunks_material_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_course_id", table_name="document_chunks")
    op.drop_table("document_chunks")
