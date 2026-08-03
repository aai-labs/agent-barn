"""merge heads

Revision ID: 609f9a8a428f
Revises: b3f7c1d92a04, b7f3d8e1c4a9
Create Date: 2026-08-03 01:34:56.519631

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "609f9a8a428f"
down_revision: str | Sequence[str] | None = ("b3f7c1d92a04", "b7f3d8e1c4a9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
