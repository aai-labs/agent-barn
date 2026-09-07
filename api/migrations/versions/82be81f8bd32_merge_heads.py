"""merge heads

Revision ID: 82be81f8bd32
Revises: 50400a4c8a00, d5a48a7fe943
Create Date: 2026-09-07 18:53:01.747123

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '82be81f8bd32'
down_revision: Union[str, None] = ('50400a4c8a00', 'd5a48a7fe943')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
