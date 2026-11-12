"""Persist logout revocations across application processes."""

from alembic import op
import sqlalchemy as sa

revision = "20261110_0010"
down_revision = "20261106_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revoked_access_tokens",
        sa.Column("token_id", sa.String(length=36), primary_key=True),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "ix_revoked_access_tokens_expires_at", "revoked_access_tokens", ["expires_at"]
    )


def downgrade() -> None:
    op.drop_table("revoked_access_tokens")
