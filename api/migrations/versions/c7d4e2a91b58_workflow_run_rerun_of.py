"""Record which workflow run a re-run repeats.

Revision ID: c7d4e2a91b58
Revises: cd22e37ca5b8
"""

import sqlalchemy as sa
from alembic import op

revision = "c7d4e2a91b58"
down_revision = "cd22e37ca5b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workflow_run", sa.Column("rerun_of_run_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_workflow_run_rerun_of_run_id",
        "workflow_run",
        "workflow_run",
        ["rerun_of_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_workflow_run_rerun_of_run_id", "workflow_run", ["rerun_of_run_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_run_rerun_of_run_id", table_name="workflow_run")
    op.drop_constraint("fk_workflow_run_rerun_of_run_id", "workflow_run", type_="foreignkey")
    op.drop_column("workflow_run", "rerun_of_run_id")
