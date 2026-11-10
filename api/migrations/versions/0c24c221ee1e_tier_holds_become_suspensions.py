"""Tier holds become suspensions that each domain owns

Revision ID: 0c24c221ee1e
Revises: 38de1199ae19
Create Date: 2026-11-10

A held Agent, Connection, Agent Webhook or Agent Memory is now suspended, with the reason
beside it. `tier_held_at` becomes `suspended_at` and `memory_tier_held_at` becomes
`memory_suspended_at`; every row already held gets the reason `tier`. Nothing else moves, so
what was held stays held.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0c24c221ee1e"
down_revision: str | Sequence[str] | None = "38de1199ae19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, held column, suspended column, reason column)
_COLUMNS = (
    ("agent", "tier_held_at", "suspended_at", "suspension_reason"),
    ("agent", "memory_tier_held_at", "memory_suspended_at", "memory_suspension_reason"),
    ("communication_connection", "tier_held_at", "suspended_at", "suspension_reason"),
    ("agent_webhook", "tier_held_at", "suspended_at", "suspension_reason"),
)


def upgrade() -> None:
    for table, held, suspended, reason in _COLUMNS:
        op.alter_column(table, held, new_column_name=suspended)
        op.add_column(table, sa.Column(reason, sa.String(length=16), nullable=True))
        op.execute(sa.text(f"UPDATE {table} SET {reason} = 'tier' WHERE {suspended} IS NOT NULL"))


def downgrade() -> None:
    # Only Tier holds existed before; a suspension for any other reason has no place to go
    # and is lifted.
    for table, held, suspended, reason in reversed(_COLUMNS):
        op.execute(sa.text(f"UPDATE {table} SET {suspended} = NULL WHERE {reason} IS DISTINCT FROM 'tier'"))
        op.drop_column(table, reason)
        op.alter_column(table, suspended, new_column_name=held)
