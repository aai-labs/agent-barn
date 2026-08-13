"""merge heads

Revision ID: 8c1e9cda45e3
Revises: 8c68a090f9c7, e2b6d9f1a4c7
Create Date: 2026-08-14 09:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "8c1e9cda45e3"
down_revision: str | Sequence[str] | None = ("8c68a090f9c7", "e2b6d9f1a4c7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
