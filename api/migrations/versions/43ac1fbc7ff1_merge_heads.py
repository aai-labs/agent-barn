"""merge heads

Revision ID: 43ac1fbc7ff1
Revises: 269470c99a40, d4f1a8c2e3b7

"""

from collections.abc import Sequence

revision: str = "43ac1fbc7ff1"
down_revision: str | Sequence[str] | None = ("269470c99a40", "d4f1a8c2e3b7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
