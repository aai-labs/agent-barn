"""merge platform admin and staging heads

Revision ID: f8d2c3e4b5a6
Revises: f7a8b9c0d1e2, ad8b4a278dd1
Create Date: 2026-07-28 00:00:00.000000

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "f8d2c3e4b5a6"
down_revision: Union[str, Sequence[str], None] = ("f7a8b9c0d1e2", "ad8b4a278dd1")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
