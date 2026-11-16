"""Record where a workflow approval was decided, and the Slack user who decided it there.

Revision ID: f3a393c5d1e2
Revises: e4b439a1c7d2
"""

import sqlalchemy as sa
from alembic import op

revision: str = "f3a393c5d1e2"
down_revision: str | None = "e4b439a1c7d2"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("workflow_approval_request", sa.Column("decision_source", sa.String(), nullable=True))
    op.add_column("workflow_approval_request", sa.Column("decided_by_slack_user_id", sa.String(), nullable=True))
    op.add_column("workflow_approval_request", sa.Column("decided_by_slack_handle", sa.String(), nullable=True))
    # Every decision before this revision was made on the web.
    op.execute("UPDATE workflow_approval_request SET decision_source = 'web' WHERE decided_at IS NOT NULL")
    op.create_check_constraint(
        "ck_workflow_approval_request_decision_source",
        "workflow_approval_request",
        "decision_source IS NULL OR decision_source IN ('web','slack')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_workflow_approval_request_decision_source", "workflow_approval_request", type_="check")
    op.drop_column("workflow_approval_request", "decided_by_slack_handle")
    op.drop_column("workflow_approval_request", "decided_by_slack_user_id")
    op.drop_column("workflow_approval_request", "decision_source")
