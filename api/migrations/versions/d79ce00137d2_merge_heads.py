"""Join staging's two histories with the Agent Bots history.

Revision ID: d79ce00137d2
Revises: 6409cd279f40, a3f5c8e1d7b2, e5b81c3d9a27
Create Date: 2026-11-09 16:09:03.356737

No schema or data operations: preserves the independently applied histories.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "d79ce00137d2"
down_revision: str | tuple[str, ...] | None = ("6409cd279f40", "a3f5c8e1d7b2", "e5b81c3d9a27")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
