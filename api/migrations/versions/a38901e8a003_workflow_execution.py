"""Durable workflow runs, Agent-session attempts, text checkpoints.

Revision ID: a38901e8a003
Revises: c32e42bb0396
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a38901e8a003"
down_revision = "c32e42bb0396"
branch_labels = None
depends_on = None


def base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def fk(name: str, target: str, delete: str = "RESTRICT", nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(target, ondelete=delete), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "workflow_run",
        *base(),
        fk("workflow_id", "workflow.id", "CASCADE"),
        fk("version_id", "workflow_version.id", "CASCADE"),
        fk("initiating_user_id", "user.id", "SET NULL", True),
        fk("initiating_membership_id", "user_organization.id", "SET NULL", True),
        sa.Column("client_request_id", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("inputs", JSONB, nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("next_step", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("runtime", sa.String(), nullable=False),
        sa.Column("reason", sa.String()),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        sa.Column("content_expired", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("workflow_id", "client_request_id", name="uq_workflow_run_start"),
        sa.CheckConstraint("revision >= 1 AND next_step >= 0 AND generation >= 0", name="ck_workflow_run_counters"),
        sa.CheckConstraint(
            "state IN ('QUEUED','RUNNING','PAUSED','BLOCKED','CANCELLING','CANCELLED','SUCCEEDED','FAILED')",
            name="ck_workflow_run_state",
        ),
    )
    op.create_index("ix_workflow_run_workflow_id", "workflow_run", ["workflow_id"])
    op.create_table(
        "workflow_attempt",
        *base(),
        fk("run_id", "workflow_run.id", "CASCADE"),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("capability_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("result_hash", sa.String()),
        sa.UniqueConstraint("run_id", "generation", name="uq_workflow_attempt_generation"),
        sa.CheckConstraint("generation >= 1 AND step_index >= 0", name="ck_workflow_attempt_counters"),
        sa.CheckConstraint(
            "state IN ('REASONING','STOPPING','STOPPED','COMPLETED','FAILED')", name="ck_workflow_attempt_state"
        ),
    )
    op.create_index("ix_workflow_attempt_run_id", "workflow_attempt", ["run_id"])
    op.create_table(
        "workflow_checkpoint",
        *base(),
        fk("run_id", "workflow_run.id", "CASCADE"),
        fk("attempt_id", "workflow_attempt.id", "CASCADE"),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("result", JSONB, nullable=False),
        sa.UniqueConstraint("run_id", "step_index", name="uq_workflow_checkpoint_step"),
    )
    op.create_index("ix_workflow_checkpoint_run_id", "workflow_checkpoint", ["run_id"])
    op.create_table(
        "workflow_history",
        *base(),
        fk("run_id", "workflow_run.id", "CASCADE"),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=False),
    )
    op.create_index("ix_workflow_history_run_id", "workflow_history", ["run_id"])
    # Cross-resource scope is derived, and cannot be forged even by a direct writer.
    op.execute("""CREATE FUNCTION workflow_execution_scope_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_TABLE_NAME = 'workflow_run' THEN
        IF NOT EXISTS (SELECT 1 FROM workflow_version v WHERE v.id=NEW.version_id AND v.workflow_id=NEW.workflow_id) THEN RAISE EXCEPTION 'workflow version scope mismatch'; END IF;
        IF TG_OP = 'INSERT' AND NOT EXISTS (
          SELECT 1 FROM user_organization m JOIN workflow w ON w.id=NEW.workflow_id JOIN agent a ON a.id=w.agent_id
          WHERE m.id=NEW.initiating_membership_id AND m.user_id=NEW.initiating_user_id AND m.organization_id=a.organization_id
        ) THEN RAISE EXCEPTION 'workflow initiating membership scope mismatch'; END IF;
        IF TG_OP = 'UPDATE' THEN
          IF NEW.workflow_id <> OLD.workflow_id OR NEW.version_id <> OLD.version_id OR NEW.client_request_id <> OLD.client_request_id OR NEW.request_hash <> OLD.request_hash OR NEW.runtime <> OLD.runtime THEN RAISE EXCEPTION 'workflow run pins are immutable'; END IF;
          IF NEW.inputs IS DISTINCT FROM OLD.inputs AND NOT (NEW.content_expired AND NEW.inputs = '{}'::jsonb) THEN RAISE EXCEPTION 'workflow run inputs are immutable'; END IF;
          IF NEW.initiating_user_id IS DISTINCT FROM OLD.initiating_user_id AND NEW.initiating_user_id IS NOT NULL THEN RAISE EXCEPTION 'workflow initiator is immutable'; END IF;
          IF NEW.initiating_membership_id IS DISTINCT FROM OLD.initiating_membership_id AND NEW.initiating_membership_id IS NOT NULL THEN RAISE EXCEPTION 'workflow membership pin is immutable'; END IF;
        END IF;
      ELSE
        IF NOT EXISTS (SELECT 1 FROM workflow_attempt a WHERE a.id=NEW.attempt_id AND a.run_id=NEW.run_id) THEN RAISE EXCEPTION 'workflow attempt scope mismatch'; END IF;
        IF TG_OP = 'UPDATE' AND (NEW.run_id <> OLD.run_id OR NEW.attempt_id <> OLD.attempt_id) THEN RAISE EXCEPTION 'workflow evidence ownership is immutable'; END IF;
      END IF;
      RETURN NEW;
    END $$""")
    for table in ("workflow_run", "workflow_checkpoint"):
        op.execute(
            f"CREATE TRIGGER {table}_scope_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION workflow_execution_scope_guard()"
        )


def downgrade() -> None:
    for table in ("workflow_history", "workflow_checkpoint", "workflow_attempt", "workflow_run"):
        op.drop_table(table)
    op.execute("DROP FUNCTION workflow_execution_scope_guard()")
