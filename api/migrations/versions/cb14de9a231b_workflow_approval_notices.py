"""Send approval requests: a workflow's Slack recipient and each request's direct message.

Revision ID: cb14de9a231b
Revises: 463f987cd60d
"""

import sqlalchemy as sa
from alembic import op

revision: str = "cb14de9a231b"
down_revision: str | None = "463f987cd60d"
branch_labels: str | None = None
depends_on: str | None = None

_WORKFLOW_CHECK = (
    "NOT approval_notice_enabled OR (approval_notice_platform = 'slack' "
    "AND approval_notice_user_id IS NOT NULL AND approval_notice_team_id IS NOT NULL)"
)


def upgrade() -> None:
    op.add_column(
        "workflow",
        sa.Column("approval_notice_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("workflow", sa.Column("approval_notice_platform", sa.String(length=32), nullable=True))
    op.add_column("workflow", sa.Column("approval_notice_user_id", sa.String(length=32), nullable=True))
    op.add_column("workflow", sa.Column("approval_notice_user_name", sa.String(length=255), nullable=True))
    op.add_column("workflow", sa.Column("approval_notice_team_id", sa.String(length=32), nullable=True))
    op.create_check_constraint("ck_workflow_approval_notice", "workflow", _WORKFLOW_CHECK)
    op.create_table(
        "workflow_approval_notice",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("platform", sa.String(), nullable=False),
        sa.Column("slack_user_id", sa.String(), nullable=False),
        sa.Column("slack_team_id", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("channel_id", sa.String(), nullable=True),
        sa.Column("message_ts", sa.String(), nullable=True),
        sa.Column("shown_state", sa.String(), nullable=True),
        sa.Column("outcome", sa.String(length=100), nullable=True),
        sa.CheckConstraint("state IN ('PENDING','SENT','SKIPPED','FAILED')", name="ck_workflow_approval_notice_state"),
        sa.ForeignKeyConstraint(["request_id"], ["workflow_approval_request.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["workflow_run.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["communication_connection.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_id"),
    )
    op.create_index("ix_workflow_approval_notice_run_id", "workflow_approval_notice", ["run_id"])


def downgrade() -> None:
    # Messages already posted stay in Slack as they are; nothing updates them afterwards.
    op.drop_index("ix_workflow_approval_notice_run_id", table_name="workflow_approval_notice")
    op.drop_table("workflow_approval_notice")
    op.drop_constraint("ck_workflow_approval_notice", "workflow", type_="check")
    op.drop_column("workflow", "approval_notice_team_id")
    op.drop_column("workflow", "approval_notice_user_name")
    op.drop_column("workflow", "approval_notice_user_id")
    op.drop_column("workflow", "approval_notice_platform")
    op.drop_column("workflow", "approval_notice_enabled")
