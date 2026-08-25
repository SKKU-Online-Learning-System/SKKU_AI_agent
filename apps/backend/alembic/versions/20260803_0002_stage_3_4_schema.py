"""Reconcile the merged stage 3 and 4 schema.

Revision ID: 20260803_0002
Revises: 20260803_0004
Create Date: 2026-08-03
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260803_0002"
down_revision: Optional[str] = "20260803_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_answer_source_values = "'rag', 'general_llm', 'safety_response', 'no_material'"


def upgrade() -> None:
    with op.batch_alter_table("chat_logs") as batch_op:
        batch_op.alter_column(
            "model_name", existing_type=sa.String(120), nullable=True
        )
        batch_op.alter_column(
            "response_time_ms", existing_type=sa.Integer(), nullable=True
        )
        batch_op.add_column(
            sa.Column(
                "answer_source_type",
                sa.String(length=32),
                server_default="rag",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "chat_answer_source_type",
            f"answer_source_type IN ({_answer_source_values})",
        )
    op.create_index("ix_chat_logs_created_at", "chat_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_logs_created_at", table_name="chat_logs")
    with op.batch_alter_table("chat_logs") as batch_op:
        batch_op.drop_constraint("chat_answer_source_type", type_="check")
        batch_op.drop_column("answer_source_type")
        batch_op.alter_column(
            "response_time_ms", existing_type=sa.Integer(), nullable=False
        )
        batch_op.alter_column(
            "model_name", existing_type=sa.String(120), nullable=False
        )
