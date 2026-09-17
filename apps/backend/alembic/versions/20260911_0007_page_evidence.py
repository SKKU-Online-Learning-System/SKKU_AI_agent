"""Persist question-independent page readings alongside their source image."""
from alembic import op
import sqlalchemy as sa

revision = "20260911_0007"
down_revision = "20260911_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("page_evidence", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "page_evidence")
