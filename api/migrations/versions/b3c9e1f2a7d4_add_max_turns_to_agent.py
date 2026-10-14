"""Add the Agent's own Hermes turn limit.

Revision ID: b3c9e1f2a7d4
Revises: aea750215df8
"""

import sqlalchemy as sa
from alembic import op

revision: str = "b3c9e1f2a7d4"
down_revision: str = "aea750215df8"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    # NULL follows the platform default, so existing Agents keep the limit they had.
    op.add_column("agent", sa.Column("max_turns", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent", "max_turns")
