"""Join the workflow run re-run link and staging's per-Agent file sync history.

Revision ID: 921deb774e01
Revises: 63c0e8364607, c7d4e2a91b58

No schema or data operations: preserves both independently applied histories.
"""

revision = "921deb774e01"
down_revision = ("63c0e8364607", "c7d4e2a91b58")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
