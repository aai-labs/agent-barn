"""merge heads

Revision ID: ed009c1e7a7c
Revises: 3faf5ff99e14, d1a390e7b2c4
Create Date: 2026-11-13 12:10:48.675217

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ed009c1e7a7c'
down_revision: Union[str, None] = ('3faf5ff99e14', 'd1a390e7b2c4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
