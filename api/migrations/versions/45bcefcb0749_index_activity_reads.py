"""index communication_delivery and agent_chat_message for Organization activity

Per-Agent time-range indexes for the Organization activity read (AF-346), which
otherwise seq-scanned both tables. Measurements are in
docs/features/business-value/CHANGELOG.md ("Activity indexes").

Revision ID: 45bcefcb0749
Revises: 1045836844da
Create Date: 2026-09-30

"""

from collections.abc import Sequence

from alembic import op

revision: str = "45bcefcb0749"
down_revision: str | Sequence[str] | None = "1045836844da"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_communication_delivery_agent_direction_completed",
        "communication_delivery",
        ["agent_id", "direction", "completed_at"],
    )
    op.create_index(
        "ix_agent_chat_message_agent_direction_occurred",
        "agent_chat_message",
        ["agent_id", "direction", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_chat_message_agent_direction_occurred", table_name="agent_chat_message")
    op.drop_index("ix_communication_delivery_agent_direction_completed", table_name="communication_delivery")
