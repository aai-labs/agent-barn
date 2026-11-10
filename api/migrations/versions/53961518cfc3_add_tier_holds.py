"""Hold what an Organization's Tier no longer covers

Revision ID: 53961518cfc3
Revises: 9b0aec4da777
Create Date: 2026-11-08

Tiers, PR 3: `tier_held_at` on an Agent, a Connection and an Agent Webhook, and
`memory_tier_held_at` on an Agent, record that the Organization's Tier stopped covering it.
A held Agent is stopped and can't start; a held Connection, Webhook or Agent Memory is
switched off. Nothing is deleted, and every column starts NULL, so nothing is held until a
Tier change holds it.

The Organization Permission `tier_hold.manage` lets Owners and Admins choose which Agents
stay held.
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "53961518cfc3"
down_revision: str | Sequence[str] | None = "9b0aec4da777"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here rather than imported: a migration must keep meaning what it meant when
# it shipped, whatever the catalogue in code says later.
TIER_HOLD_MANAGE_ID = UUID("f236e2c1-a221-559e-946b-9c25232caa30")
TIER_HOLD_MANAGE_KEY = "tier_hold.manage"
_HELD_COLUMNS = (
    ("agent", "tier_held_at"),
    ("agent", "memory_tier_held_at"),
    ("communication_connection", "tier_held_at"),
    ("agent_webhook", "tier_held_at"),
)


def _with_catalogue_unlocked(statement: sa.TextClause, **params: object) -> None:
    """The Permission catalogue is immutable by trigger; a migration is the one place
    allowed to change it, and it locks it again in the same transaction."""
    op.execute("ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability")
    op.get_bind().execute(statement, params)
    op.execute("ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability")


def upgrade() -> None:
    for table, column in _HELD_COLUMNS:
        op.add_column(table, sa.Column(column, sa.DateTime(timezone=True), nullable=True))
    _with_catalogue_unlocked(
        sa.text(
            "INSERT INTO permissions (id, created_at, updated_at, key) "
            "VALUES (:id, now(), now(), :key) ON CONFLICT DO NOTHING"
        ),
        id=TIER_HOLD_MANAGE_ID,
        key=TIER_HOLD_MANAGE_KEY,
    )


def downgrade() -> None:
    _with_catalogue_unlocked(sa.text("DELETE FROM permissions WHERE id = :id"), id=TIER_HOLD_MANAGE_ID)
    for table, column in reversed(_HELD_COLUMNS):
        op.drop_column(table, column)
