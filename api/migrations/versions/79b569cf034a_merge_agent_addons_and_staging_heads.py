"""Join Agent Add-ons and staging migration histories.

Revision ID: 79b569cf034a
Revises: 00cdd18a6e91, 6fe963719ec9

No schema or data operations: preserves both independently applied histories.
"""

revision = "79b569cf034a"
down_revision = ("00cdd18a6e91", "6fe963719ec9")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
