"""Record Agent Memory cost origin without storing tenant content.

Revision ID: e4c9b72a6f10
Revises: d7f4a92c1e83
Create Date: 2026-10-03
"""

import sqlalchemy as sa
from alembic import op

revision = "e4c9b72a6f10"
down_revision = "d7f4a92c1e83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cost_record", sa.Column("is_memory", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("cost_record", "is_memory")
