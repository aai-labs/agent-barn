"""Join staging's Agent Tasks history with the Agent Bots history.

Revision ID: 3faf5ff99e14
Revises: a9d2e7c4b1f8, d79ce00137d2
Create Date: 2026-11-13

No schema or data operations: preserves the independently applied histories.
"""

from collections.abc import Sequence

revision: str = "3faf5ff99e14"
down_revision: str | tuple[str, ...] | None = ("a9d2e7c4b1f8", "d79ce00137d2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
