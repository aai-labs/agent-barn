"""merge AF-363 per-agent runtime pin with staging memory cleanup

Revision ID: be043fdf21b3
Revises: 2482afb7a62b, f03a9c61d872
Create Date: 2026-10-06 15:14:27.347999

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'be043fdf21b3'
down_revision: Union[str, None] = ('2482afb7a62b', 'f03a9c61d872')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
