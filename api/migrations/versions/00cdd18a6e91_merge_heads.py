"""Join environment health and artifact storage migration histories.

Revision ID: 00cdd18a6e91
Revises: 05548c9db068, fac0030afc38

No schema or data operations: preserves both independently applied histories.
"""

revision = "00cdd18a6e91"
down_revision = ("05548c9db068", "fac0030afc38")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
