"""Reconcile the chat log grounded default and the document chunk constraint name.

Revision ID: 20260907_0006
Revises: 20260825_0005
Create Date: 2026-09-07
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260907_0006"
down_revision: Optional[str] = "20260825_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHUNK_UNIQUE_COLUMNS = ["material_id", "chunk_index"]


def _rename_chunk_unique_constraint(old_name: str, new_name: str) -> None:
    """Rename the document chunk unique constraint, keeping its index if possible."""
    if op.get_bind().dialect.name == "postgresql":
        # Renaming leaves the backing index alone. Dropping and recreating the
        # constraint would rebuild it and hold a lock for as long as that takes.
        op.execute(
            f"ALTER TABLE document_chunks RENAME CONSTRAINT {old_name} TO {new_name}"
        )
        return

    # SQLite has no RENAME CONSTRAINT; batch mode recreates the table instead.
    with op.batch_alter_table("document_chunks") as batch_op:
        batch_op.drop_constraint(old_name, type_="unique")
        batch_op.create_unique_constraint(new_name, _CHUNK_UNIQUE_COLUMNS)


def upgrade() -> None:
    # The model has always declared server_default="false" here, but the
    # creating migration left it out, so anything inserting without the ORM
    # (bulk loads, restores, psql) hits a NOT NULL violation the app never sees.
    with op.batch_alter_table("chat_logs") as batch_op:
        batch_op.alter_column(
            "is_grounded",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.text("false"),
        )
    _rename_chunk_unique_constraint(
        "uq_document_chunks_material_index",
        "uq_document_chunks_material_chunk_index",
    )


def downgrade() -> None:
    _rename_chunk_unique_constraint(
        "uq_document_chunks_material_chunk_index",
        "uq_document_chunks_material_index",
    )
    with op.batch_alter_table("chat_logs") as batch_op:
        batch_op.alter_column(
            "is_grounded",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=None,
        )
