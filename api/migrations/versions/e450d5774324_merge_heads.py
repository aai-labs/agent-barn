"""Join the Discord require-mention retirement and staging's Agent file sync histories.

Revision ID: e450d5774324
Revises: 16ac819db080, cd22e37ca5b8

No schema or data operations: preserves both independently applied histories.
"""

revision = "e450d5774324"
down_revision = ("16ac819db080", "cd22e37ca5b8")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
