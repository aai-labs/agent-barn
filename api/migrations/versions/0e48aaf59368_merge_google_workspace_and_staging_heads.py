"""merge google workspace and staging heads

Revision ID: 0e48aaf59368
Revises: b7e2c4d81f39, 04088157c78c
Create Date: 2026-08-18

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0e48aaf59368"
down_revision: str | Sequence[str] | None = ("b7e2c4d81f39", "04088157c78c")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
