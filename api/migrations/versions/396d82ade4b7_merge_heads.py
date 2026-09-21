"""merge heads

Revision ID: 396d82ade4b7
Revises: c8e1f4a9b2d6, d5e7a1c3b902
Create Date: 2026-09-17 09:45:41.959709

"""

from collections.abc import Sequence

revision: str = "396d82ade4b7"
down_revision: str | Sequence[str] | None = ("c8e1f4a9b2d6", "d5e7a1c3b902")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
