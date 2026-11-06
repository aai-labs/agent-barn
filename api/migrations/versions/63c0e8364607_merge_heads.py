"""Join the per-Agent file sync switch and staging's merged history.

Revision ID: 63c0e8364607
Revises: cd22e37ca5b8, df10528f512f

No schema or data operations: preserves both independently applied histories.
"""

revision = "63c0e8364607"
down_revision = ("cd22e37ca5b8", "df10528f512f")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
