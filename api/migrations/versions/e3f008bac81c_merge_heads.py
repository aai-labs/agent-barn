"""merge heads

Revision ID: e3f008bac81c
Revises: b3d8e1f4a6c2, f1aac76e927a
Create Date: 2026-10-12 10:46:12.850727

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3f008bac81c'
down_revision: Union[str, None] = ('b3d8e1f4a6c2', 'f1aac76e927a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
