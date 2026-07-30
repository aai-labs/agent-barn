"""merge_shared_credentials_and_staging_heads

Revision ID: dee13d2cd664
Revises: 4934b7713177, c4d5e6f7a8b9
Create Date: 2026-07-30 11:32:59.312063

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "dee13d2cd664"
down_revision: Union[str, tuple[str, str], None] = ("4934b7713177", "c4d5e6f7a8b9")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
