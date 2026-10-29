"""Join staging's file-sync and workflow re-run migration histories.

Revision ID: e700d800fb8a
Revises: 63c0e8364607, c7d4e2a91b58

No schema or data operations; both parent histories remain intact.
"""

revision = "e700d800fb8a"
down_revision = ("63c0e8364607", "c7d4e2a91b58")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
