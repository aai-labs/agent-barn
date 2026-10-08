"""agentbarn telegram connection secret

Revision ID: 164fb0fb6c2c
Revises: fcdc690dbf31
Create Date: 2026-10-08 09:50:01.269143

Each Agent Barn Telegram Connection's random root secret, from which its Agent's
stand-in Bot API token and webhook secret are derived. It replaces the retired
Connection driver key. The table is new, so there is no data to migrate: a
Connection gets its secret when its Agent next starts.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "164fb0fb6c2c"
down_revision: str | Sequence[str] | None = "fcdc690dbf31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agentbarn_telegram_connection_secret",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["connection_id"], ["communication_connection.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("connection_id", name="uq_agentbarn_telegram_connection_secret_connection"),
    )


def downgrade() -> None:
    op.drop_table("agentbarn_telegram_connection_secret")
