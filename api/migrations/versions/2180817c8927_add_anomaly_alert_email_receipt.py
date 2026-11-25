"""Add anomaly alert email receipts

Revision ID: 2180817c8927
Revises: 92996d692c89
Create Date: 2026-11-25

Owners and Admins are emailed when a check flags unusual activity worth a look. One
alert's Event Delivery emails several people; a receipt per recipient lets a retry
email only those it did not reach.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2180817c8927"
down_revision: str | Sequence[str] | None = "92996d692c89"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "anomaly_alert_email_receipt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.ForeignKeyConstraint(["delivery_id"], ["event_delivery.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id", "recipient_email", name="uq_anomaly_alert_email_receipt_delivery_recipient"),
    )
    op.create_index(
        "ix_anomaly_alert_email_receipt_delivery_id",
        "anomaly_alert_email_receipt",
        ["delivery_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_anomaly_alert_email_receipt_delivery_id", table_name="anomaly_alert_email_receipt")
    op.drop_table("anomaly_alert_email_receipt")
