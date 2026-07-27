"""Add Agent lifecycle email receipt for per-recipient handler idempotency.

Revision ID: d1e2f3a4b5c6
Revises: c9d8e7f6a5b4
Create Date: 2026-07-27

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c9d8e7f6a5b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_lifecycle_email_receipt",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.ForeignKeyConstraint(["delivery_id"], ["event_delivery.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "delivery_id", "recipient_email", name="uq_agent_lifecycle_email_receipt_delivery_recipient"
        ),
    )
    op.create_index("ix_agent_lifecycle_email_receipt_delivery", "agent_lifecycle_email_receipt", ["delivery_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_lifecycle_email_receipt_delivery", table_name="agent_lifecycle_email_receipt")
    op.drop_table("agent_lifecycle_email_receipt")
