"""Workflow approval requests and the Awaiting Approval run state.

Revision ID: d1a390e7b2c4
Revises: a9d2e7c4b1f8
"""

import sqlalchemy as sa
from alembic import op

revision: str = "d1a390e7b2c4"
down_revision: str | None = "a9d2e7c4b1f8"
branch_labels: str | None = None
depends_on: str | None = None

_OLD = "state IN ('QUEUED','RUNNING','PAUSED','BLOCKED','CANCELLING','CANCELLED','SUCCEEDED','FAILED')"
_NEW = (
    "state IN ('QUEUED','RUNNING','PAUSED','BLOCKED','AWAITING_APPROVAL','CANCELLING','CANCELLED','SUCCEEDED','FAILED')"
)


def upgrade() -> None:
    op.drop_constraint("ck_workflow_run_state", "workflow_run", type_="check")
    op.create_check_constraint("ck_workflow_run_state", "workflow_run", _NEW)
    op.create_table(
        "workflow_approval_request",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("runtime_run_id", sa.String(), nullable=False),
        sa.Column("command", sa.String(), nullable=False),
        sa.Column("command_sha256", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("live_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("guidance", sa.String(), nullable=True),
        sa.Column("continued_by_attempt_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "state IN ('LIVE','PARKED','APPROVED','DECLINED','RELEASED','LAPSED')",
            name="ck_workflow_approval_request_state",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attempt_id"], ["workflow_attempt.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["continued_by_attempt_id"], ["workflow_attempt.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workflow_approval_request_run_id", "workflow_approval_request", ["run_id"])
    op.create_index(
        "ix_workflow_approval_request_open",
        "workflow_approval_request",
        ["run_id"],
        postgresql_where=sa.text("state IN ('LIVE','PARKED')"),
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_approval_request_open", table_name="workflow_approval_request")
    op.drop_index("ix_workflow_approval_request_run_id", table_name="workflow_approval_request")
    op.drop_table("workflow_approval_request")
    # Parked runs cannot be represented by the older constraint; block them for a person instead.
    op.execute(
        "UPDATE workflow_run SET state = 'BLOCKED', "
        "reason = 'Awaiting approval; approval support was rolled back' WHERE state = 'AWAITING_APPROVAL'"
    )
    op.drop_constraint("ck_workflow_run_state", "workflow_run", type_="check")
    op.create_check_constraint("ck_workflow_run_state", "workflow_run", _OLD)
