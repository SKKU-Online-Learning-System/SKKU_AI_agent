"""Cache the AI study note written for each lecture page beside its evidence."""
from alembic import op
import sqlalchemy as sa

revision = "20261106_0009"
down_revision = "20261006_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("page_note", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "page_note")
