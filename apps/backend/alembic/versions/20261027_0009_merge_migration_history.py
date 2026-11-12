"""Join the legacy index migrations and the visual/usage migrations.

Restore both histories without rewriting revisions already applied to existing databases.
"""

revision = "20261027_0009"
down_revision = ("20260907_0007", "20261006_0008")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
