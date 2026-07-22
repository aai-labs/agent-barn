"""add approval_mode to agent

Revision ID: b1c2d3e4f5a6
Revises: c89367ccd358
Create Date: 2026-07-03

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "c89367ccd358"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("approval_mode", sa.String(10), nullable=True))
    op.execute("UPDATE agent SET approval_mode = 'auto' WHERE approval_mode IS NULL")
    op.alter_column("agent", "approval_mode", nullable=False)


def downgrade() -> None:
    op.drop_column("agent", "approval_mode")
