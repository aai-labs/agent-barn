"""Approval steps: rounds at an Approval step, step results per round and the Rejected run state.

Revision ID: b7e2c41d9a63
Revises: c87b17ccfe1a
"""

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2c41d9a63"
down_revision: str | None = "c87b17ccfe1a"
branch_labels: str | None = None
depends_on: str | None = None

_OLD = (
    "state IN ('QUEUED','RUNNING','PAUSED','BLOCKED','AWAITING_APPROVAL','CANCELLING','CANCELLED','SUCCEEDED','FAILED')"
)
_NEW = (
    "state IN ('QUEUED','RUNNING','PAUSED','BLOCKED','AWAITING_APPROVAL','CANCELLING','CANCELLED',"
    "'SUCCEEDED','FAILED','REJECTED')"
)


def upgrade() -> None:
    op.drop_constraint("ck_workflow_run_state", "workflow_run", type_="check")
    op.create_check_constraint("ck_workflow_run_state", "workflow_run", _NEW)

    # A step that runs again after Request changes keeps its earlier result as a superseded round.
    op.add_column("workflow_checkpoint", sa.Column("round", sa.Integer(), server_default="1", nullable=False))
    op.add_column("workflow_checkpoint", sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("workflow_checkpoint", "round", server_default=None)
    op.drop_constraint("uq_workflow_checkpoint_step", "workflow_checkpoint", type_="unique")
    op.create_unique_constraint(
        "uq_workflow_checkpoint_round", "workflow_checkpoint", ["run_id", "step_index", "round"]
    )
    op.create_check_constraint("ck_workflow_checkpoint_round", "workflow_checkpoint", "round >= 1")

    op.create_table(
        "workflow_step_approval",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.String(), nullable=True),
        sa.CheckConstraint("round >= 1 AND step_index >= 1", name="ck_workflow_step_approval_counters"),
        sa.CheckConstraint(
            "state IN ('WAITING','APPROVED','CHANGES_REQUESTED','REJECTED','LAPSED')",
            name="ck_workflow_step_approval_state",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "step_index", "round", name="uq_workflow_step_approval_round"),
    )
    op.create_index("ix_workflow_step_approval_run_id", "workflow_step_approval", ["run_id"])
    op.create_index(
        "uq_workflow_step_approval_waiting",
        "workflow_step_approval",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("state = 'WAITING'"),
    )


def downgrade() -> None:
    # The older API cannot represent a run waiting at an Approval step or a rejected run.
    op.execute(
        "UPDATE workflow_run SET state = 'CANCELLED', settled_at = coalesce(settled_at, now()), "
        "reason = 'Waiting at an Approval step; approval step support was rolled back' "
        "WHERE state = 'AWAITING_APPROVAL' AND id IN "
        "(SELECT run_id FROM workflow_step_approval WHERE state = 'WAITING')"
    )
    op.execute(
        "UPDATE workflow_run SET state = 'FAILED', reason = coalesce(reason, 'Rejected at an Approval step') "
        "WHERE state = 'REJECTED'"
    )
    op.drop_index("uq_workflow_step_approval_waiting", table_name="workflow_step_approval")
    op.drop_index("ix_workflow_step_approval_run_id", table_name="workflow_step_approval")
    op.drop_table("workflow_step_approval")

    # Only the current round of each step fits the older one-result-per-step constraint.
    op.execute("DELETE FROM workflow_checkpoint WHERE superseded_at IS NOT NULL")
    op.execute(
        "DELETE FROM workflow_checkpoint c USING workflow_checkpoint newer "
        "WHERE newer.run_id = c.run_id AND newer.step_index = c.step_index AND newer.round > c.round"
    )
    op.drop_constraint("ck_workflow_checkpoint_round", "workflow_checkpoint", type_="check")
    op.drop_constraint("uq_workflow_checkpoint_round", "workflow_checkpoint", type_="unique")
    op.create_unique_constraint("uq_workflow_checkpoint_step", "workflow_checkpoint", ["run_id", "step_index"])
    op.drop_column("workflow_checkpoint", "superseded_at")
    op.drop_column("workflow_checkpoint", "round")

    op.drop_constraint("ck_workflow_run_state", "workflow_run", type_="check")
    op.create_check_constraint("ck_workflow_run_state", "workflow_run", _OLD)
