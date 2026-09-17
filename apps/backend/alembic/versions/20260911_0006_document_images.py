"""Keep the rendered source page with each visual chunk."""
from alembic import op
import sqlalchemy as sa

revision = "20260911_0006"
down_revision = "20260825_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_chunks", sa.Column("page_image", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("document_chunks", "page_image")
