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
    op.alter_column("chat_logs", "model_name", existing_type=sa.String(120), nullable=True)
    op.alter_column("chat_logs", "response_time_ms", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "chat_logs",
        sa.Column(
            "answer_source_type",
            sa.String(length=32),
            server_default="rag",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "chat_answer_source_type",
        "chat_logs",
        f"answer_source_type IN ({_answer_source_values})",
    )
    op.create_index("ix_chat_logs_created_at", "chat_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_chat_logs_created_at", table_name="chat_logs")
    op.drop_constraint("chat_answer_source_type", "chat_logs", type_="check")
    op.drop_column("chat_logs", "answer_source_type")
    op.alter_column("chat_logs", "response_time_ms", existing_type=sa.Integer(), nullable=False)
    op.alter_column("chat_logs", "model_name", existing_type=sa.String(120), nullable=False)
