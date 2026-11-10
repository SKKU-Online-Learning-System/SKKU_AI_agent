"""Merge legacy PostgreSQL/SQLite migrations with the current application head."""

revision = "20261110_0011"
down_revision = ("20261027_0009", "20261110_0010")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
