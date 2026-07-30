"""Add event Outbox Message persistence.

Revision ID: b4c7e2a19d34
Revises: a7b8c9d0e1f2
Create Date: 2026-07-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4c7e2a19d34"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_outbox_message",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_name", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("subject", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("causation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_event_outbox_message_event_id"),
    )
    op.create_index(
        "ix_event_outbox_message_name_version",
        "event_outbox_message",
        ["event_name", "schema_version"],
    )
    op.create_index(
        "ix_event_outbox_message_organization_occurred",
        "event_outbox_message",
        ["organization_id", "occurred_at"],
    )
    op.execute(
        """
        CREATE FUNCTION prevent_event_outbox_message_update()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'event_outbox_message rows are immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_prevent_event_outbox_message_update
        BEFORE UPDATE ON event_outbox_message
        FOR EACH ROW EXECUTE FUNCTION prevent_event_outbox_message_update();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_event_outbox_message_update ON event_outbox_message")
    op.execute("DROP FUNCTION IF EXISTS prevent_event_outbox_message_update()")
    op.drop_index("ix_event_outbox_message_organization_occurred", table_name="event_outbox_message")
    op.drop_index("ix_event_outbox_message_name_version", table_name="event_outbox_message")
    op.drop_table("event_outbox_message")
