"""merge skills and templates migrations

Revision ID: fd1b1a0bdd6e
Revises: 032ff9a474bb, c2d3e4f5a6b7
Create Date: 2026-06-17 17:30:21.699920

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "fd1b1a0bdd6e"
down_revision: Union[str, None] = ("032ff9a474bb", "c2d3e4f5a6b7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
