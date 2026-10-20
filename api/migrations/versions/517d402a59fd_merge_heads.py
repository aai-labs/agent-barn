"""merge heads

Revision ID: 517d402a59fd
Revises: 8e5c1f3a9b27, dc378bacdf04
Create Date: 2026-10-20 08:51:17.761110

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "517d402a59fd"
down_revision: str | Sequence[str] | None = ("8e5c1f3a9b27", "dc378bacdf04")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
