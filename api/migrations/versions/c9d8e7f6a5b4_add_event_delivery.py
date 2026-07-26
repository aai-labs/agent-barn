"""Add Event Delivery persistence.

Revision ID: c9d8e7f6a5b4
Revises: b4c7e2a19d34
Create Date: 2026-07-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d8e7f6a5b4"
down_revision: Union[str, None] = "b4c7e2a19d34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

event_delivery_status_enum = postgresql.ENUM(
    "PENDING",
    "ENQUEUED",
    "PROCESSING",
    "SUCCEEDED",
    "DEAD_LETTERED",
    name="eventdeliverystatus",
    create_type=False,
)


def upgrade() -> None:
    event_delivery_status_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "event_delivery",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("outbox_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("handler_name", sa.String(length=255), nullable=False),
        sa.Column("status", event_delivery_status_enum, nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["outbox_message_id"], ["event_outbox_message.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "handler_name", name="uq_event_delivery_event_handler"),
    )
    op.create_index("ix_event_delivery_outbox_message", "event_delivery", ["outbox_message_id"])
    op.create_index("ix_event_delivery_organization_status", "event_delivery", ["organization_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_event_delivery_organization_status", table_name="event_delivery")
    op.drop_index("ix_event_delivery_outbox_message", table_name="event_delivery")
    op.drop_table("event_delivery")
    event_delivery_status_enum.drop(op.get_bind(), checkfirst=True)
