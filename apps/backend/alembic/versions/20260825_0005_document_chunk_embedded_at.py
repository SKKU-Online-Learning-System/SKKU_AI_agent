"""Add the document chunk embedding timestamp.

Revision ID: 20260825_0005
Revises: 20260803_0002
Create Date: 2026-08-25
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260825_0005"
down_revision: Optional[str] = "20260803_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_chunks", "embedded_at")
