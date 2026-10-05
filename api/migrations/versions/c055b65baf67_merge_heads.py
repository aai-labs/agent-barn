"""merge heads

Revision ID: c055b65baf67
Revises: d7a2c4f81b36, e4b9d72c160a
Create Date: 2026-10-05 17:45:31.492286

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c055b65baf67'
down_revision: Union[str, None] = ('d7a2c4f81b36', 'e4b9d72c160a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
