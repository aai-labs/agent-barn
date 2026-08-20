"""add pinned_version to agent_skill

Revision ID: 5f6e7d8c9b0a
Revises: 8c1e9cda45e3
Create Date: 2026-08-15 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5f6e7d8c9b0a"
down_revision: str | None = "8c1e9cda45e3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_skill", sa.Column("pinned_version", sa.Integer(), nullable=True))
    # Backfill every existing assignment to the skill's then-latest version so
    # current behavior is frozen, not lost.
    op.execute(
        """
        UPDATE agent_skill AS assignment
        SET pinned_version = latest.version
        FROM (
            SELECT skill_id, MAX(version) AS version
            FROM skill_version
            GROUP BY skill_id
        ) AS latest
        WHERE latest.skill_id = assignment.skill_id
        """
    )
    op.execute("UPDATE agent_skill SET pinned_version = 1 WHERE pinned_version IS NULL")
    op.alter_column("agent_skill", "pinned_version", nullable=False)
    # Composite FK so a version pinned by any agent cannot be deleted at the DB
    # level, and a pin can never reference a nonexistent version. NO ACTION keeps
    # the safety net for direct version deletes while allowing sibling cascades
    # (for example, organization deletion) to remove the assignment first.
    op.create_foreign_key(
        "fk_agent_skill_pinned_version",
        "agent_skill",
        "skill_version",
        ["skill_id", "pinned_version"],
        ["skill_id", "version"],
        ondelete="NO ACTION",
    )


def downgrade() -> None:
    op.drop_constraint("fk_agent_skill_pinned_version", "agent_skill", type_="foreignkey")
    op.drop_column("agent_skill", "pinned_version")
