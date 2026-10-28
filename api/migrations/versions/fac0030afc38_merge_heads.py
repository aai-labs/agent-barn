"""Join per-Agent artifact storage and staging's Agent Size history.

Revision ID: fac0030afc38
Revises: 8b2e4f61c9d3, a4152d0e1f32

No schema or data operations: preserves both independently applied histories.
"""

revision = "fac0030afc38"
down_revision = ("8b2e4f61c9d3", "a4152d0e1f32")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
