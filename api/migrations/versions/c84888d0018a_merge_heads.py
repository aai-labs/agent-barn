"""Join the agent task and staging restore point histories.

Revision ID: c84888d0018a
Revises: 6409cd279f40, a3f5c8e1d7b2

No schema or data operations; preserves both histories.
"""

from collections.abc import Sequence

revision: str = "c84888d0018a"
down_revision: str | tuple[str, ...] | None = ("6409cd279f40", "a3f5c8e1d7b2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
