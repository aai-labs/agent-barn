"""add mutable platform baseline to organization template forks

Revision ID: 01a32822566b
Revises: 1d191f9ef700
Create Date: 2026-08-03 00:00:00.000000

The existing forked_from_platform_template_id records where an organization
fork was originally created. A separate baseline is required so a later
Template Update can advance the last-synced platform version without losing
the original fork provenance.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "01a32822566b"
down_revision: str | Sequence[str] | None = "1d191f9ef700"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_template",
        sa.Column("fork_baseline_platform_template_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_template_fork_baseline",
        "agent_template",
        "platform_template",
        ["fork_baseline_platform_template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_agent_template_fork_baseline_platform_template_id",
        "agent_template",
        ["fork_baseline_platform_template_id"],
    )
    # Existing org forks were created from the row already recorded by the
    # origin pointer, so their last-synced baseline is unambiguous.
    op.execute(
        sa.text(
            """
            UPDATE agent_template
            SET fork_baseline_platform_template_id = forked_from_platform_template_id
            WHERE forked_from_platform_template_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_template_fork_baseline_platform_template_id",
        table_name="agent_template",
    )
    op.drop_constraint("fk_agent_template_fork_baseline", "agent_template", type_="foreignkey")
    op.drop_column("agent_template", "fork_baseline_platform_template_id")
