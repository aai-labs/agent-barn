"""replace agent template_id with org-scoped template_slug lineage

Revision ID: a4d7c2e8f1b3
Revises: 0dfb8ab409db
Create Date: 2026-06-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4d7c2e8f1b3"
down_revision: str | None = "0dfb8ab409db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_template",
        sa.Column("template_slug", sa.String(length=255), nullable=True),
    )

    # Rows sharing an agent_id form one lineage: slugify the agent's name and
    # append the first 8 hex chars of the agent id (stable per lineage, same
    # shape as the runtime generator).
    op.execute(
        """
        UPDATE agent_template t
        SET template_slug =
            COALESCE(
                NULLIF(
                    trim(both '-' from
                        lower(regexp_replace(a.name, '[^a-zA-Z0-9]+', '-', 'g'))
                    ),
                    ''
                ) || '-',
                ''
            ) || substr(replace(a.id::text, '-', ''), 1, 8)
        FROM agent a
        WHERE t.agent_id = a.id
        """
    )
    # Orphans (agent_id IS NULL: non-current versions predating e9b4f23c5a71)
    # were already unreachable; a per-row slug keeps them unique.
    op.execute(
        """
        UPDATE agent_template
        SET template_slug = 'orphan-' || substr(replace(id::text, '-', ''), 1, 8)
        WHERE template_slug IS NULL
        """
    )
    op.alter_column("agent_template", "template_slug", nullable=False)
    op.create_unique_constraint(
        "uq_agent_template_org_slug_version",
        "agent_template",
        ["organization_id", "template_slug", "version"],
    )

    op.add_column("agent", sa.Column("template_slug", sa.String(length=255), nullable=True))
    # Re-sync template_version from the referenced row as well, so the
    # composite FK below cannot fail on historically drifted data.
    op.execute(
        """
        UPDATE agent a
        SET template_slug = t.template_slug,
            template_version = t.version
        FROM agent_template t
        WHERE a.template_id = t.id
        """
    )
    op.alter_column("agent", "template_slug", nullable=False)

    op.create_foreign_key(
        "fk_agent_template_slug_version",
        "agent",
        "agent_template",
        ["organization_id", "template_slug", "template_version"],
        ["organization_id", "template_slug", "version"],
        ondelete="RESTRICT",
    )

    op.drop_index("ix_agent_template_agent_version", table_name="agent_template")
    op.drop_constraint("fk_agent_template_agent_id", "agent_template", type_="foreignkey")
    op.drop_column("agent_template", "agent_id")
    # Dropping the column also drops the unnamed FK (agent_template_id_fkey).
    op.drop_column("agent", "template_id")


def downgrade() -> None:
    op.add_column("agent", sa.Column("template_id", sa.Uuid(), nullable=True))
    op.add_column("agent_template", sa.Column("agent_id", sa.Uuid(), nullable=True))

    op.execute(
        """
        UPDATE agent a
        SET template_id = t.id
        FROM agent_template t
        WHERE t.organization_id = a.organization_id
          AND t.template_slug = a.template_slug
          AND t.version = a.template_version
        """
    )
    # Orphan slugs match no agent and stay NULL (their pre-upgrade state).
    op.execute(
        """
        UPDATE agent_template t
        SET agent_id = a.id
        FROM agent a
        WHERE a.organization_id = t.organization_id
          AND a.template_slug = t.template_slug
        """
    )
    op.alter_column("agent", "template_id", nullable=False)

    op.create_foreign_key(
        "agent_template_id_fkey",
        "agent",
        "agent_template",
        ["template_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key("fk_agent_template_agent_id", "agent_template", "agent", ["agent_id"], ["id"])
    op.create_index("ix_agent_template_agent_version", "agent_template", ["agent_id", "version"])

    op.drop_constraint("fk_agent_template_slug_version", "agent", type_="foreignkey")
    op.drop_column("agent", "template_slug")
    op.drop_constraint("uq_agent_template_org_slug_version", "agent_template", type_="unique")
    op.drop_column("agent_template", "template_slug")
