"""Join Agent file sync and staging's environment health and artifact storage histories.

Revision ID: cd22e37ca5b8
Revises: 00cdd18a6e91, af95cf4c3a1e

No schema or data operations: preserves both independently applied histories.
"""

revision = "cd22e37ca5b8"
down_revision = ("00cdd18a6e91", "af95cf4c3a1e")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
