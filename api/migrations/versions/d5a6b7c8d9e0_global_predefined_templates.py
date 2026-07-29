"""global predefined templates

Revision ID: d5a6b7c8d9e0
Revises: c6d7e8f9a0b1
Create Date: 2026-07-28 00:00:00.000000

Predefined templates become true platform/global resources (organization_id IS
NULL), mirroring built-in aai_cli skills. Custom templates stay
organization-scoped. The agent's org-scoped composite FK to agent_template is
dropped because a global predefined row can never satisfy an agent-scoped FK;
template existence is enforced at the service boundary instead.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5a6b7c8d9e0"
down_revision: Union[str, None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. The agent's composite FK assumes every template is org-scoped. Global
    #    predefined rows (organization_id IS NULL) can never satisfy it, so the
    #    FK contract is replaced by service-layer existence checks.
    op.drop_constraint("fk_agent_template_slug_version", "agent", type_="foreignkey")

    # 2. Allow global predefined rows: organization_id becomes nullable, and the
    #    old org-scoped unique constraint is replaced by scope-aware partial
    #    unique indexes.
    op.drop_constraint("uq_agent_template_org_slug_version", "agent_template", type_="unique")
    op.alter_column(
        "agent_template",
        "organization_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=True,
    )

    # 3. Collapse the per-org predefined v1 copies into a single global row per
    #    slug. Org-edited predefined lineages (version > 1) stay org-scoped, so a
    #    lineage becomes global v1 + org-scoped v2+. Agents pin by
    #    (template_slug, template_version) and need no re-pointing.
    bind = op.get_bind()

    # 3a. Drop the required-skill refs on per-org predefined v1 duplicates. Every
    #     org is seeded identically, so the canonical (smallest id) row already
    #     carries the same skills; any hand-edited drift is reconciled by the
    #     global seeder on next startup, which resyncs the v1 required skills.
    bind.execute(
        sa.text(
            """
            DELETE FROM agent_template_skill ats
            USING agent_template dup, agent_template canonical
            WHERE dup.template_source = 'pre-defined'
              AND dup.version = 1
              AND canonical.template_source = 'pre-defined'
              AND canonical.version = 1
              AND canonical.template_slug = dup.template_slug
              AND canonical.id < dup.id
              AND ats.template_id = dup.id
            """
        )
    )

    # 3b. Delete the duplicate predefined v1 rows, then make every surviving
    #     predefined v1 row global.
    bind.execute(
        sa.text(
            """
            DELETE FROM agent_template dup
            USING agent_template canonical
            WHERE dup.template_source = 'pre-defined'
              AND dup.version = 1
              AND canonical.template_source = 'pre-defined'
              AND canonical.version = 1
              AND canonical.template_slug = dup.template_slug
              AND canonical.id < dup.id
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE agent_template
            SET organization_id = NULL
            WHERE template_source = 'pre-defined'
              AND version = 1
            """
        )
    )

    # 4. Scope-aware uniqueness: one global predefined row per (slug, version),
    #    and one org-scoped row per (org, slug, version).
    op.create_index(
        "uq_agent_template_global_slug_version",
        "agent_template",
        ["template_slug", "version"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.create_index(
        "uq_agent_template_org_slug_version",
        "agent_template",
        ["organization_id", "template_slug", "version"],
        unique=True,
        postgresql_where=sa.text("organization_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_agent_template_org_slug_version", table_name="agent_template")
    op.drop_index("uq_agent_template_global_slug_version", table_name="agent_template")

    # Re-scope the surviving predefined v1 rows back to their first owning org if
    # any agent pins them; rows with no pinning agent are dropped (no org owns
    # them in the downgraded model).
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE agent_template t
            SET organization_id = sub.organization_id
            FROM (
                SELECT DISTINCT ON (a.template_slug)
                       a.template_slug, a.organization_id
                FROM agent a
                WHERE a.template_version = 1
                ORDER BY a.template_slug, a.created_at
            ) sub
            WHERE t.template_source = 'pre-defined'
              AND t.version = 1
              AND t.organization_id IS NULL
              AND t.template_slug = sub.template_slug
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM agent_template
            WHERE template_source = 'pre-defined'
              AND version = 1
              AND organization_id IS NULL
            """
        )
    )

    op.alter_column(
        "agent_template",
        "organization_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_agent_template_org_slug_version",
        "agent_template",
        ["organization_id", "template_slug", "version"],
    )
    op.create_foreign_key(
        "fk_agent_template_slug_version",
        "agent",
        "agent_template",
        ["organization_id", "template_slug", "template_version"],
        ["organization_id", "template_slug", "version"],
        ondelete="RESTRICT",
    )
