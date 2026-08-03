"""Add course material week and make uploads immediately available.

Revision ID: 20260721_0002
Revises: 20260710_0001
Create Date: 2026-07-21
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260721_0002"
down_revision: Optional[str] = "20260710_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("course_materials") as batch_op:
        batch_op.add_column(
            sa.Column("week", sa.SmallInteger(), server_default="1", nullable=False)
        )
        batch_op.create_check_constraint(
            "ck_course_materials_week_range",
            "week >= 1 AND week <= 16",
        )
        batch_op.alter_column(
            "processing_status",
            existing_type=sa.String(length=10),
            server_default="completed",
        )
    op.execute(
        "UPDATE course_materials SET processing_status = 'completed' "
        "WHERE processing_status IN ('pending', 'processing')"
    )


def downgrade() -> None:
    with op.batch_alter_table("course_materials") as batch_op:
        batch_op.alter_column(
            "processing_status",
            existing_type=sa.String(length=10),
            server_default="pending",
        )
        batch_op.drop_constraint("ck_course_materials_week_range", type_="check")
        batch_op.drop_column("week")
