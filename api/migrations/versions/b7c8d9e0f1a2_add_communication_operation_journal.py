"""add communication operation journal

Revision ID: b7c8d9e0f1a2
Revises: f39d7aa422be
Create Date: 2026-08-26 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | Sequence[str] | None = "f39d7aa422be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Identity columns intentionally have no foreign keys. The journal is
    # operational history and must remain queryable after a product row is
    # retired or removed.
    op.create_table(
        "communication_operation_journal",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=True),
        sa.Column("attempt_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_summary", sa.String(length=500), nullable=True),
        sa.CheckConstraint("attempt_number >= 0", name="ck_communication_journal_attempt_number"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_communication_journal_connection_occurred",
        "communication_operation_journal",
        ["connection_id", "occurred_at"],
    )
    op.create_index(
        "ix_communication_journal_delivery_occurred",
        "communication_operation_journal",
        ["delivery_id", "occurred_at"],
    )
    op.create_index(
        "ix_communication_journal_agent_occurred",
        "communication_operation_journal",
        ["agent_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_communication_journal_agent_occurred",
        table_name="communication_operation_journal",
    )
    op.drop_index(
        "ix_communication_journal_delivery_occurred",
        table_name="communication_operation_journal",
    )
    op.drop_index(
        "ix_communication_journal_connection_occurred",
        table_name="communication_operation_journal",
    )
    op.drop_table("communication_operation_journal")
