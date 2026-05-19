"""add model to agent

Revision ID: d8a3f12b4c59
Revises: c5f2a1e8d047
Create Date: 2026-05-18

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8a3f12b4c59"
down_revision: Union[str, None] = "c5f2a1e8d047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("model", sa.Text(), nullable=True))
    op.execute("UPDATE agent SET model = '' WHERE model IS NULL")
    op.alter_column("agent", "model", nullable=False)


def downgrade() -> None:
    op.drop_column("agent", "model")
