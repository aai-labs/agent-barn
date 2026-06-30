"""merge multiple heads

Revision ID: 777879d0a4c9
Revises: 59a9b94c4299, 7e2a9c4b1d63
Create Date: 2026-06-29 12:25:11.759594

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '777879d0a4c9'
down_revision: Union[str, None] = ('59a9b94c4299', '7e2a9c4b1d63')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
