"""Add document chunks and pending material processing.

Revision ID: 20260724_0003
Revises: 20260721_0002
Create Date: 2026-07-24
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260724_0003"
down_revision: Optional[str] = "20260721_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
            name="uq_document_chunks_material_index",
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
    with op.batch_alter_table("course_materials") as batch_op:
        batch_op.alter_column(
            "processing_status",
            existing_type=sa.String(length=10),
            server_default="pending",
        )
    op.execute(
        "UPDATE course_materials SET processing_status = 'pending', processing_error = NULL "
        "WHERE processing_status = 'completed'"
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_material_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_course_id", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.execute(
        "UPDATE course_materials SET processing_status = 'completed' "
        "WHERE processing_status = 'pending'"
    )
    with op.batch_alter_table("course_materials") as batch_op:
        batch_op.alter_column(
            "processing_status",
            existing_type=sa.String(length=10),
            server_default="completed",
        )
