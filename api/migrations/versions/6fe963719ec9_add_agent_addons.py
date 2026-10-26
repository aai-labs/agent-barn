"""Add Agent Add-ons

Revision ID: 6fe963719ec9
Revises: 8b2e4f61c9d3
Create Date: 2026-10-26

An Organization Owner or Admin requests an add-on (a pinned pip or npm package, a git
repository at a commit, a binary with its SHA-256, or a reviewed command) for one Agent, and a
Platform Administrator approves, rejects or revokes that exact request (`agent_addons`). Each
notification Event Delivery records whom it emailed (`agent_addon_email_receipt`). An Agent
records the approved set its running pod installed (`agent.running_addons_hash`, NULL when it
has none or is not running), which is how a set approved or revoked since reads as pending.

No Agent has an add-on yet, so every existing row keeps a NULL hash and nothing reads as
pending. `agent.addon.manage` is added to the Permission catalogue; Organization Owners and
Admins hold it through their role, from code.
"""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6fe963719ec9"
down_revision: str | Sequence[str] | None = "8b2e4f61c9d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen here rather than imported: a migration must keep meaning what it meant when
# it shipped, whatever the catalogue in code says later.
AGENT_ADDON_MANAGE_ID = UUID("8b81242c-14ec-5777-9619-da649a795dda")
AGENT_ADDON_MANAGE_KEY = "agent.addon.manage"


def _with_catalogue_unlocked(statement: sa.TextClause, **params: object) -> None:
    """The Permission catalogue is immutable by trigger; a migration is the one place
    allowed to change it, and it locks it again in the same transaction."""
    op.execute("ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability")
    op.get_bind().execute(statement, params)
    op.execute("ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability")


def upgrade() -> None:
    op.create_table(
        "agent_addons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(214), nullable=False),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("state", sa.String(16), server_default="PENDING", nullable=False),
        sa.Column("requested_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_addons_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "state IN ('PENDING', 'APPROVED', 'REJECTED', 'WITHDRAWN', 'REVOKED')", name="ck_agent_addons_state"
        ),
        sa.CheckConstraint("kind IN ('pip', 'npm', 'git', 'binary', 'command')", name="ck_agent_addons_kind"),
        sa.CheckConstraint(
            "(state = 'REJECTED') = (rejection_reason IS NOT NULL)", name="ck_agent_addons_rejection_reason"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # One active add-on per kind and name on an Agent: two would install over each other.
    op.create_index(
        "uq_agent_addons_active_name",
        "agent_addons",
        ["agent_id", "kind", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("state IN ('PENDING', 'APPROVED')"),
    )
    op.create_index("ix_agent_addons_agent_state", "agent_addons", ["agent_id", "state"])
    op.create_index("ix_agent_addons_state_created", "agent_addons", ["state", "created_at"])
    op.create_index("ix_agent_addons_organization", "agent_addons", ["organization_id"])

    op.create_table(
        "agent_addon_email_receipt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_id", "recipient_email", name="uq_agent_addon_email_receipt_delivery_recipient"),
    )
    op.create_index("ix_agent_addon_email_receipt_delivery_id", "agent_addon_email_receipt", ["delivery_id"])

    op.add_column("agent", sa.Column("running_addons_hash", sa.String(64), nullable=True))

    _with_catalogue_unlocked(
        sa.text(
            "INSERT INTO permissions (id, created_at, updated_at, key) "
            "VALUES (:id, now(), now(), :key) ON CONFLICT DO NOTHING"
        ),
        id=AGENT_ADDON_MANAGE_ID,
        key=AGENT_ADDON_MANAGE_KEY,
    )


def downgrade() -> None:
    _with_catalogue_unlocked(sa.text("DELETE FROM permissions WHERE id = :id"), id=AGENT_ADDON_MANAGE_ID)

    op.drop_column("agent", "running_addons_hash")
    op.drop_table("agent_addon_email_receipt")
    op.drop_index("ix_agent_addons_organization", table_name="agent_addons")
    op.drop_index("ix_agent_addons_state_created", table_name="agent_addons")
    op.drop_index("ix_agent_addons_agent_state", table_name="agent_addons")
    op.drop_index("uq_agent_addons_active_name", table_name="agent_addons")
    op.drop_table("agent_addons")
