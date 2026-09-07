"""merge cost_record and verbose mode heads

Revision ID: d5a48a7fe943
Revises: a4b5c6d7e8f9, c3f1a7d2e9b4
Create Date: 2026-09-07

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d5a48a7fe943"
down_revision: str | Sequence[str] | None = ("a4b5c6d7e8f9", "c3f1a7d2e9b4")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
