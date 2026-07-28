"""split predefined templates into platform_template table

Revision ID: e6b7c8d9e0f1
Revises: d5a6b7c8d9e0
Create Date: 2026-07-28 00:00:00.000000

Predefined templates move out of the org-scoped agent_template table into a
dedicated global platform_template table (no organization_id), mirroring the
built-in skill model with real referential integrity. agent_template becomes
strictly organization-scoped again (custom templates + org forks of predefined
templates). Org forks record their origin via forked_from_platform_template_id.
Agents pin a template version through one of two mutually-exclusive FKs
(platform_template_id / agent_template_id) with a CHECK guard, replacing the
loose (template_slug, template_version) pin columns.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6b7c8d9e0f1"
down_revision: Union[str, None] = "d5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Global platform template catalogue.
    op.create_table(
        "platform_template",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("template_slug", sa.String(length=255), nullable=False),
        sa.Column("template_name", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("soul_md", sa.Text(), nullable=False),
        sa.Column("identity_md", sa.Text(), nullable=False),
        sa.Column("user_md", sa.Text(), nullable=False),
        sa.Column("tools_md", sa.Text(), nullable=False),
        sa.Column("agents_md", sa.Text(), nullable=False),
        sa.Column("boot_md", sa.Text(), nullable=False),
        sa.Column("bootstrap_md", sa.Text(), nullable=False),
        sa.Column("heartbeat_md", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_slug", "version", name="uq_platform_template_slug_version"),
    )

    op.create_table(
        "platform_template_skill",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("template_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", sa.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["template_id"], ["platform_template.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("template_id", "skill_id", name="uq_platform_template_skill"),
        sa.Index("ix_platform_template_skill_template", "template_id"),
    )

    # 2. Move the global predefined rows (organization_id IS NULL) from
    #    agent_template into platform_template. The id is preserved so existing
    #    agent_template_skill rows can be re-pointed by value.
    bind.execute(
        sa.text(
            """
            INSERT INTO platform_template (
                id, created_at, updated_at,
                template_slug, template_name, version, description,
                soul_md, identity_md, user_md, tools_md, agents_md,
                boot_md, bootstrap_md, heartbeat_md
            )
            SELECT
                id, created_at, updated_at,
                template_slug, template_name, version, description,
                soul_md, identity_md, user_md, tools_md, agents_md,
                boot_md, bootstrap_md, heartbeat_md
            FROM agent_template
            WHERE organization_id IS NULL AND template_source = 'pre-defined'
            """
        )
    )

    # 3. Move the required-skill refs for those rows into platform_template_skill,
    #    then drop the originals from agent_template_skill.
    bind.execute(
        sa.text(
            """
            INSERT INTO platform_template_skill (id, created_at, updated_at, template_id, skill_id)
            SELECT id, created_at, updated_at, template_id, skill_id
            FROM agent_template_skill
            WHERE template_id IN (
                SELECT id FROM agent_template WHERE organization_id IS NULL AND template_source = 'pre-defined'
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM agent_template_skill
            WHERE template_id IN (
                SELECT id FROM agent_template WHERE organization_id IS NULL AND template_source = 'pre-defined'
            )
            """
        )
    )

    # 4. Delete the now-migrated global rows from agent_template.
    bind.execute(
        sa.text("DELETE FROM agent_template WHERE organization_id IS NULL AND template_source = 'pre-defined'")
    )

    # 5. agent_template is strictly org-scoped again: record fork lineage, then
    #    tighten organization_id back to NOT NULL and restore a normal unique
    #    constraint (replacing the scope-aware partial indexes).
    op.add_column(
        "agent_template",
        sa.Column(
            "forked_from_platform_template_id",
            sa.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_agent_template_forked_from",
        "agent_template",
        "platform_template",
        ["forked_from_platform_template_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Org-scoped predefined rows are forks; point them at the platform v1 row of
    # the same slug so the lineage relationship is explicit and "update
    # available" detection is possible later.
    bind.execute(
        sa.text(
            """
            UPDATE agent_template t
            SET forked_from_platform_template_id = pt.id
            FROM platform_template pt
            WHERE t.template_source = 'pre-defined'
              AND t.organization_id IS NOT NULL
              AND pt.template_slug = t.template_slug
              AND pt.version = 1
            """
        )
    )

    op.alter_column(
        "agent_template",
        "organization_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=False,
    )
    op.drop_index("uq_agent_template_global_slug_version", table_name="agent_template")
    op.drop_index("uq_agent_template_org_slug_version", table_name="agent_template")
    op.create_unique_constraint(
        "uq_agent_template_org_slug_version",
        "agent_template",
        ["organization_id", "template_slug", "version"],
    )

    # 6. Re-pin agents via two mutually-exclusive FKs. The old pin columns
    #    (template_slug, template_version) are replaced by exactly one of
    #    platform_template_id / agent_template_id, restoring DB-level
    #    referential integrity.
    op.add_column("agent", sa.Column("platform_template_id", sa.UUID(as_uuid=True), nullable=True))
    op.add_column("agent", sa.Column("agent_template_id", sa.UUID(as_uuid=True), nullable=True))

    # Org-scoped pin (custom template or org fork) first.
    bind.execute(
        sa.text(
            """
            UPDATE agent a
            SET agent_template_id = t.id
            FROM agent_template t
            WHERE t.organization_id = a.organization_id
              AND t.template_slug = a.template_slug
              AND t.version = a.template_version
            """
        )
    )
    # Remaining agents pin a global predefined template (now in platform_template).
    bind.execute(
        sa.text(
            """
            UPDATE agent a
            SET platform_template_id = pt.id
            FROM platform_template pt
            WHERE a.agent_template_id IS NULL
              AND pt.template_slug = a.template_slug
              AND pt.version = a.template_version
            """
        )
    )

    op.create_foreign_key(
        "fk_agent_platform_template",
        "agent",
        "platform_template",
        ["platform_template_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_agent_agent_template",
        "agent",
        "agent_template",
        ["agent_template_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_agent_exactly_one_template_pin",
        "agent",
        "(platform_template_id IS NULL) <> (agent_template_id IS NULL)",
    )

    # 7. Drop the legacy loose pin columns.
    op.drop_column("agent", "template_slug")
    op.drop_column("agent", "template_version")


def downgrade() -> None:
    bind = op.get_bind()

    # Restore the loose pin columns and populate them from whichever FK is set.
    op.add_column("agent", sa.Column("template_slug", sa.String(length=255), nullable=True))
    op.add_column("agent", sa.Column("template_version", sa.Integer(), nullable=True))

    bind.execute(
        sa.text(
            """
            UPDATE agent a
            SET template_slug = t.template_slug, template_version = t.version
            FROM agent_template t
            WHERE a.agent_template_id = t.id
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE agent a
            SET template_slug = pt.template_slug, template_version = pt.version
            FROM platform_template pt
            WHERE a.platform_template_id = pt.id
            """
        )
    )
    op.alter_column("agent", "template_slug", existing_type=sa.String(length=255), nullable=False)
    op.alter_column("agent", "template_version", existing_type=sa.Integer(), nullable=False)

    op.drop_constraint("ck_agent_exactly_one_template_pin", "agent", type_="check")
    op.drop_constraint("fk_agent_agent_template", "agent", type_="foreignkey")
    op.drop_constraint("fk_agent_platform_template", "agent", type_="foreignkey")
    op.drop_column("agent", "agent_template_id")
    op.drop_column("agent", "platform_template_id")

    # Loosen agent_template back to the scope-aware model: nullable org_id and
    # partial unique indexes.
    op.drop_constraint("uq_agent_template_org_slug_version", "agent_template", type_="unique")
    op.alter_column(
        "agent_template",
        "organization_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=True,
    )
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

    op.drop_constraint("fk_agent_template_forked_from", "agent_template", type_="foreignkey")
    op.drop_column("agent_template", "forked_from_platform_template_id")

    # Move platform_template rows back to agent_template as global predefined
    # rows, and their skill refs back to agent_template_skill.
    bind.execute(
        sa.text(
            """
            INSERT INTO agent_template (
                id, created_at, updated_at, organization_id,
                template_slug, template_name, template_source, version, description,
                soul_md, identity_md, user_md, tools_md, agents_md,
                boot_md, bootstrap_md, heartbeat_md
            )
            SELECT
                id, created_at, updated_at, NULL,
                template_slug, template_name, 'pre-defined', version, description,
                soul_md, identity_md, user_md, tools_md, agents_md,
                boot_md, bootstrap_md, heartbeat_md
            FROM platform_template
            """
        )
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO agent_template_skill (id, created_at, updated_at, template_id, skill_id)
            SELECT id, created_at, updated_at, template_id, skill_id
            FROM platform_template_skill
            """
        )
    )

    op.drop_index("ix_platform_template_skill_template", table_name="platform_template_skill")
    op.drop_table("platform_template_skill")
    op.drop_table("platform_template")
