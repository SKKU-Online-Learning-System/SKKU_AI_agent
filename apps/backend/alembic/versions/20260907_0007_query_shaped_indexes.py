"""Replace single-column indexes with the composites the queries actually use.

Revision ID: 20260907_0007
Revises: 20260907_0006
Create Date: 2026-09-07
"""

from typing import Optional, Sequence, Union

from alembic import op

revision: str = "20260907_0007"
down_revision: Optional[str] = "20260907_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (index name, table, columns) for indexes whose leading column already had one.
_PROMOTED = (
    ("ix_chat_logs_course_id_created_at", "chat_logs", ["course_id", "created_at"]),
    ("ix_chat_logs_user_id_created_at", "chat_logs", ["user_id", "created_at"]),
    ("ix_chat_logs_session_id_created_at", "chat_logs", ["session_id", "created_at"]),
    (
        "ix_course_materials_course_id_created_at",
        "course_materials",
        ["course_id", "created_at"],
    ),
)
_SUPERSEDED = (
    ("ix_chat_logs_course_id", "chat_logs"),
    ("ix_chat_logs_user_id", "chat_logs"),
    ("ix_chat_logs_session_id", "chat_logs"),
    ("ix_course_materials_course_id", "course_materials"),
    # Already the leading column of uq_document_chunks_material_chunk_index.
    ("ix_document_chunks_material_id", "document_chunks"),
)


def upgrade() -> None:
    # Create before dropping so no query is left without an index in between.
    for name, table, columns in _PROMOTED:
        op.create_index(name, table, columns)
    for name, table in _SUPERSEDED:
        op.drop_index(name, table_name=table)


def downgrade() -> None:
    for name, table in _SUPERSEDED:
        column = name.removeprefix(f"ix_{table}_")
        op.create_index(name, table, [column])
    for name, table, _columns in _PROMOTED:
        op.drop_index(name, table_name=table)
