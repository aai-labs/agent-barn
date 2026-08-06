"""normalize organization fork versions and store platform baseline version

Revision ID: f6a7b8c9d0e1
Revises: d222461d5cd9
Create Date: 2026-08-04 00:00:00.000000

Organization fork versions are an organization-owned sequence. Existing rows
created by the previous platform-relative scheme are renumbered in creation
order without changing their immutable IDs, so existing agent pins remain
unchanged.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | Sequence[str] | None = "d222461d5cd9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_template",
        sa.Column("fork_baseline_platform_version", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE agent_template t
            SET fork_baseline_platform_version = p.version
            FROM platform_template p
            WHERE p.id = COALESCE(
                t.fork_baseline_platform_template_id,
                t.forked_from_platform_template_id
            )
            """
        )
    )

    # Normalize the old platform-relative versions through a temporary
    # negative value so the existing organization/key/version uniqueness
    # constraint cannot collide while values are being reassigned.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        PARTITION BY organization_id, template_key
                        ORDER BY version, created_at, id
                    ) AS organization_version
                FROM agent_template
                WHERE forked_from_platform_template_id IS NOT NULL
            )
            UPDATE agent_template t
            SET version = -ranked.organization_version
            FROM ranked
            WHERE t.id = ranked.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE agent_template
            SET version = -version
            WHERE forked_from_platform_template_id IS NOT NULL
              AND version < 0
            """
        )
    )


def downgrade() -> None:
    # Restore the former platform-relative numbering for fork rows. The
    # immutable row IDs and agent foreign keys are never changed.
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    t.id,
                    p.version + ROW_NUMBER() OVER (
                        PARTITION BY t.organization_id, t.template_key
                        ORDER BY t.version, t.created_at, t.id
                    ) AS legacy_version
                FROM agent_template t
                JOIN platform_template p
                  ON p.id = t.forked_from_platform_template_id
                WHERE t.forked_from_platform_template_id IS NOT NULL
            )
            UPDATE agent_template t
            SET version = -ranked.legacy_version
            FROM ranked
            WHERE t.id = ranked.id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE agent_template
            SET version = -version
            WHERE forked_from_platform_template_id IS NOT NULL
              AND version < 0
            """
        )
    )
    op.drop_column("agent_template", "fork_baseline_platform_version")
