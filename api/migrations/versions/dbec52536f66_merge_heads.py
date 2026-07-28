"""merge heads

Revision ID: dbec52536f66
Revises: b4e7a21c9f35, dce8d344498a
Create Date: 2026-07-23 14:29:42.488647

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "dbec52536f66"
down_revision: Union[str, Sequence[str], None] = ("b4e7a21c9f35", "dce8d344498a")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
