"""Merge Agent Memory and self-service spend-limit migrations.

Preserve both already-applied development histories without resetting memory data.
"""

revision = "e94b17c62a30"
down_revision = ("d83f291bc7a0", "d7a2c4f81b36")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
