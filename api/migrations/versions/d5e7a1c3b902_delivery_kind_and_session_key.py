"""delivery kind and session key

Revision ID: d5e7a1c3b902
Revises: c4e8a2f19d73
Create Date: 2026-09-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e7a1c3b902"
down_revision: str | Sequence[str] | None = "c4e8a2f19d73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Adding a value is allowed inside a transaction on PostgreSQL 12+, as long as
    # nothing in the same transaction uses it. Nothing here does.
    op.execute(sa.text("ALTER TYPE conversationtype ADD VALUE IF NOT EXISTS 'EVENT'"))
    # A string, not a PostgreSQL enum: `direction` and `status` on this table are both
    # plain strings, and matching them keeps a future kind from needing a type change.
    op.add_column(
        "communication_delivery",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="CONVERSATION"),
    )
    # Nullable on purpose. Backfilling would mean re-deriving every historical row from
    # its JSONB envelope, and nothing reads the session key of a finished delivery. The
    # pod falls back to deriving its own when this is absent, so deliveries already in
    # flight across the deploy are unaffected.
    op.add_column(
        "communication_delivery",
        sa.Column("session_key", sa.String(length=1024), nullable=True),
    )
    op.create_index(
        "ix_communication_delivery_kind_status",
        "communication_delivery",
        ["kind", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_communication_delivery_kind_status", table_name="communication_delivery")
    op.drop_column("communication_delivery", "session_key")
    op.drop_column("communication_delivery", "kind")
    # 'EVENT' stays on conversationtype. PostgreSQL has no DROP VALUE, and the
    # recreate-cast-rename alternative first needs an answer for what existing EVENT
    # rows become -- they are neither CHANNEL nor DM. An unused enum value is inert.
