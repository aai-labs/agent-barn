"""bound communication journal retention

Revision ID: f4a9c2d7e1b6
Revises: ee946cc4a3c3
Create Date: 2026-08-28 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "f4a9c2d7e1b6"
down_revision: str | Sequence[str] | None = "ee946cc4a3c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_communication_journal_occurred",
        "communication_operation_journal",
        ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_communication_journal_occurred",
        table_name="communication_operation_journal",
    )
