"""retain pending Domain Events after Organization deletion

Revision ID: 3b7c9d1e4f62
Revises: 2a4f6c8e1b30
Create Date: 2026-08-02

"""

from collections.abc import Sequence

from alembic import op

revision: str = "3b7c9d1e4f62"
down_revision: str | None = "2a4f6c8e1b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Outbox and delivery rows are transport history, not Organization-owned
    # resources. Keep them available for the audit projection when an Organization
    # is deleted before its asynchronous delivery completes.
    for table_name in ("event_delivery", "event_outbox_message"):
        op.drop_constraint(
            f"{table_name}_organization_id_fkey",
            table_name,
            type_="foreignkey",
        )


def downgrade() -> None:
    op.create_foreign_key(
        "event_outbox_message_organization_id_fkey",
        "event_outbox_message",
        "organization",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "event_delivery_organization_id_fkey",
        "event_delivery",
        "organization",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
