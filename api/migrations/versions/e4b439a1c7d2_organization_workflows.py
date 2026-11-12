"""Workflows belong to the Organization; each run names the Agent that runs it.

Adds the `workflow.manage` Permission, held by Organization Owners and Admins.

The downgrade is lossy: a workflow keeps only one Agent (its default, else the Agent of
its latest run), and workflows with neither are deleted.

Revision ID: e4b439a1c7d2
Revises: d1a390e7b2c4
"""

from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "e4b439a1c7d2"
down_revision: str | None = "d1a390e7b2c4"
branch_labels: str | None = None
depends_on: str | None = None

# Frozen here rather than imported: a migration must keep meaning what it meant when it
# shipped, whatever the catalogue in code says later.
WORKFLOW_MANAGE_ID = UUID("c3f7a1d2-6b48-5e90-8a2c-7d4e1f9b0a56")
WORKFLOW_MANAGE_KEY = "workflow.manage"


def _with_catalogue_unlocked(statement: sa.TextClause, **params: object) -> None:
    """The Permission catalogue is immutable by trigger; a migration is the one place
    allowed to change it, and it locks it again in the same transaction."""
    op.execute("ALTER TABLE permissions DISABLE TRIGGER trg_permission_catalogue_immutability")
    op.get_bind().execute(statement, params)
    op.execute("ALTER TABLE permissions ENABLE TRIGGER trg_permission_catalogue_immutability")


_RUN_GUARD_HEAD = """CREATE OR REPLACE FUNCTION workflow_execution_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_TABLE_NAME = 'workflow_run' THEN
        IF NOT EXISTS (SELECT 1 FROM workflow_version v WHERE v.id=NEW.version_id AND v.workflow_id=NEW.workflow_id) THEN RAISE EXCEPTION 'workflow version scope mismatch'; END IF;
"""
_RUN_GUARD_TAIL = """
          IF NEW.inputs IS DISTINCT FROM OLD.inputs AND NOT (NEW.content_expired AND NEW.inputs = '{}'::jsonb) THEN RAISE EXCEPTION 'workflow run inputs are immutable'; END IF;
          IF NEW.initiating_user_id IS DISTINCT FROM OLD.initiating_user_id AND NEW.initiating_user_id IS NOT NULL THEN RAISE EXCEPTION 'workflow initiator is immutable'; END IF;
          IF NEW.initiating_membership_id IS DISTINCT FROM OLD.initiating_membership_id AND NEW.initiating_membership_id IS NOT NULL THEN RAISE EXCEPTION 'workflow membership pin is immutable'; END IF;
        END IF;
      ELSE
        IF NOT EXISTS (SELECT 1 FROM workflow_attempt a WHERE a.id=NEW.attempt_id AND a.run_id=NEW.run_id) THEN RAISE EXCEPTION 'workflow attempt scope mismatch'; END IF;
        IF TG_OP = 'UPDATE' AND (NEW.run_id <> OLD.run_id OR NEW.attempt_id <> OLD.attempt_id) THEN RAISE EXCEPTION 'workflow evidence ownership is immutable'; END IF;
      END IF;
      RETURN NEW;
    END $$"""

# The run's Agent and the initiating Membership must both be in the workflow's Organization.
_ORGANIZATION_GUARD = (
    _RUN_GUARD_HEAD
    + """        IF TG_OP = 'INSERT' AND NOT EXISTS (
          SELECT 1 FROM workflow w JOIN agent a ON a.id=NEW.agent_id AND a.organization_id=w.organization_id
          WHERE w.id=NEW.workflow_id
        ) THEN RAISE EXCEPTION 'workflow run agent scope mismatch'; END IF;
        IF TG_OP = 'INSERT' AND NOT EXISTS (
          SELECT 1 FROM user_organization m JOIN workflow w ON w.id=NEW.workflow_id
          WHERE m.id=NEW.initiating_membership_id AND m.user_id=NEW.initiating_user_id AND m.organization_id=w.organization_id
        ) THEN RAISE EXCEPTION 'workflow initiating membership scope mismatch'; END IF;
        IF TG_OP = 'UPDATE' THEN
          IF NEW.workflow_id <> OLD.workflow_id OR NEW.agent_id <> OLD.agent_id OR NEW.version_id <> OLD.version_id OR NEW.client_request_id <> OLD.client_request_id OR NEW.request_hash <> OLD.request_hash OR NEW.runtime <> OLD.runtime THEN RAISE EXCEPTION 'workflow run pins are immutable'; END IF;"""
    + _RUN_GUARD_TAIL
)
_AGENT_GUARD = (
    _RUN_GUARD_HEAD
    + """        IF TG_OP = 'INSERT' AND NOT EXISTS (
          SELECT 1 FROM user_organization m JOIN workflow w ON w.id=NEW.workflow_id JOIN agent a ON a.id=w.agent_id
          WHERE m.id=NEW.initiating_membership_id AND m.user_id=NEW.initiating_user_id AND m.organization_id=a.organization_id
        ) THEN RAISE EXCEPTION 'workflow initiating membership scope mismatch'; END IF;
        IF TG_OP = 'UPDATE' THEN
          IF NEW.workflow_id <> OLD.workflow_id OR NEW.version_id <> OLD.version_id OR NEW.client_request_id <> OLD.client_request_id OR NEW.request_hash <> OLD.request_hash OR NEW.runtime <> OLD.runtime THEN RAISE EXCEPTION 'workflow run pins are immutable'; END IF;"""
    + _RUN_GUARD_TAIL
)


def upgrade() -> None:
    op.add_column("workflow", sa.Column("organization_id", sa.Uuid(), nullable=True))
    op.add_column("workflow", sa.Column("created_by_membership_id", sa.Uuid(), nullable=True))
    op.add_column("workflow", sa.Column("default_agent_id", sa.Uuid(), nullable=True))
    op.add_column("workflow_run", sa.Column("agent_id", sa.Uuid(), nullable=True))
    op.add_column("workflow_run", sa.Column("title", sa.String(), nullable=True))

    op.execute("UPDATE workflow w SET organization_id = a.organization_id FROM agent a WHERE a.id = w.agent_id")
    # Existing workflows keep running on the Agent they were written for, unless it was deleted.
    op.execute(
        "UPDATE workflow w SET default_agent_id = a.id FROM agent a WHERE a.id = w.agent_id AND a.deleted_at IS NULL"
    )
    # Their creator becomes the Organization's Owner, else its earliest Admin.
    op.execute(
        """UPDATE workflow w SET created_by_membership_id = (
             SELECT m.id FROM user_organization m
             WHERE m.organization_id = w.organization_id AND m.role IN ('OWNER', 'ADMIN')
             ORDER BY (m.role = 'OWNER') DESC, m.created_at, m.id LIMIT 1)"""
    )
    op.execute("UPDATE workflow_run r SET agent_id = w.agent_id FROM workflow w WHERE w.id = r.workflow_id")

    op.alter_column("workflow", "organization_id", nullable=False)
    op.alter_column("workflow_run", "agent_id", nullable=False)
    op.create_foreign_key(
        "workflow_organization_id_fkey", "workflow", "organization", ["organization_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "workflow_created_by_membership_id_fkey",
        "workflow",
        "user_organization",
        ["created_by_membership_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "workflow_default_agent_id_fkey", "workflow", "agent", ["default_agent_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key(
        "workflow_run_agent_id_fkey", "workflow_run", "agent", ["agent_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_workflow_organization_id", "workflow", ["organization_id"])
    op.create_index("ix_workflow_run_agent_id", "workflow_run", ["agent_id"])

    op.execute(_ORGANIZATION_GUARD)
    op.drop_column("workflow", "agent_id")
    _with_catalogue_unlocked(
        sa.text(
            "INSERT INTO permissions (id, created_at, updated_at, key) "
            "VALUES (:id, now(), now(), :key) ON CONFLICT DO NOTHING"
        ),
        id=WORKFLOW_MANAGE_ID,
        key=WORKFLOW_MANAGE_KEY,
    )


def downgrade() -> None:
    _with_catalogue_unlocked(sa.text("DELETE FROM permissions WHERE id = :id"), id=WORKFLOW_MANAGE_ID)
    op.add_column("workflow", sa.Column("agent_id", sa.Uuid(), nullable=True))
    op.execute(
        """UPDATE workflow w SET agent_id = COALESCE(
             w.default_agent_id,
             (SELECT r.agent_id FROM workflow_run r WHERE r.workflow_id = w.id ORDER BY r.created_at DESC LIMIT 1))"""
    )
    op.execute("DELETE FROM workflow WHERE agent_id IS NULL")
    # A workflow has one Agent again, so runs made on any other Agent cannot be kept.
    op.execute("DELETE FROM workflow_run r USING workflow w WHERE w.id = r.workflow_id AND r.agent_id <> w.agent_id")
    op.alter_column("workflow", "agent_id", nullable=False)
    op.create_foreign_key("workflow_agent_id_fkey", "workflow", "agent", ["agent_id"], ["id"], ondelete="CASCADE")
    op.create_index("ix_workflow_agent_id", "workflow", ["agent_id"])
    op.execute(_AGENT_GUARD)

    op.drop_index("ix_workflow_run_agent_id", table_name="workflow_run")
    op.drop_index("ix_workflow_organization_id", table_name="workflow")
    op.drop_column("workflow_run", "title")
    op.drop_column("workflow_run", "agent_id")
    op.drop_column("workflow", "default_agent_id")
    op.drop_column("workflow", "created_by_membership_id")
    op.drop_column("workflow", "organization_id")
