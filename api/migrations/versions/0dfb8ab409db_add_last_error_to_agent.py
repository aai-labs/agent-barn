"""add last_error to agent

Revision ID: 0dfb8ab409db
Revises: f3a91c7b2e58
Branch Labels: None
Depends On: None

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0dfb8ab409db"
down_revision: Union[str, None] = "c1d2e3f4a5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("last_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent", "last_error")
