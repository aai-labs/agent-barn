"""agentbarn telegram link first message

Revision ID: a78bcde4b918
Revises: d72b85f19c40
Create Date: 2026-10-15 12:00:00.000000

When a linked Telegram user's first message was accepted for their Agent, so product
analytics reports it once per link (AF-374). Links that already existed count as
messaged from when they were made: their history is no longer available, and their
next message must not be reported as a first one.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a78bcde4b918"
down_revision: str | Sequence[str] | None = "d72b85f19c40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agentbarn_telegram_link", sa.Column("first_message_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE agentbarn_telegram_link SET first_message_at = created_at")


def downgrade() -> None:
    op.drop_column("agentbarn_telegram_link", "first_message_at")
