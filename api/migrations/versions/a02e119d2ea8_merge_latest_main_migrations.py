"""merge latest main migrations

Revision ID: a02e119d2ea8
Revises: 032ff9a474bb, 849e21682b7a
Create Date: 2026-06-30 16:34:22.121346

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "a02e119d2ea8"
down_revision: Union[str, Sequence[str], None] = ("032ff9a474bb", "849e21682b7a")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
