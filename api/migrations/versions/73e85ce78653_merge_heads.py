"""merge heads

Revision ID: 73e85ce78653
Revises: c3b7e19d4a52, e2b7c4d19a58
Create Date: 2026-09-23 19:18:12.673963

"""

from collections.abc import Sequence

revision: str = "73e85ce78653"
down_revision: str | Sequence[str] | None = ("c3b7e19d4a52", "e2b7c4d19a58")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
