"""merge heads after taking staging

Revision ID: c3b7e19d4a52
Revises: a1f42e91843f, b6d4f0a91c37
Create Date: 2026-09-22 00:00:00.000000
"""

from collections.abc import Sequence

revision: str = "c3b7e19d4a52"
down_revision: str | Sequence[str] | None = ("a1f42e91843f", "b6d4f0a91c37")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
