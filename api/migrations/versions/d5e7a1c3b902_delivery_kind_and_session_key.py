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
    op.execute(sa.text("ALTER TYPE conversationtype ADD VALUE IF NOT EXISTS 'EVENT'"))
    # A string like `direction` and `status`, not a PostgreSQL enum.
    op.add_column(
        "communication_delivery",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="CONVERSATION"),
    )
    # Nullable: nothing reads the session key of a finished delivery, and the pod derives
    # its own when this is absent, so deliveries in flight across the deploy are unaffected.
    op.add_column(
        "communication_delivery",
        sa.Column("session_key", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("communication_delivery", "session_key")
    op.drop_column("communication_delivery", "kind")
    # PostgreSQL has no DROP VALUE, so 'EVENT' stays on conversationtype.
