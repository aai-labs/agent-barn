"""merge main migrations

Revision ID: 9421ae35fdcb
Revises: a02e119d2ea8, b1c2d3e4f5a6
Create Date: 2026-07-05 13:03:34.688288

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9421ae35fdcb'
down_revision: Union[str, None] = ('a02e119d2ea8', 'b1c2d3e4f5a6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
