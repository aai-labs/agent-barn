"""add agent_template_draft

Revision ID: a2b3c4d5e6f7
Revises: 87ec190e0f7d
Create Date: 2026-09-04 00:00:00.000000

Extends the Draft Template Version concept to organization-scoped Templates
(see docs/adr/2026-09-04-organization-templates-use-draft-publish.md). Mirrors
platform_template_draft, but organization-scoped: two organizations can hold a
draft for the same forked template_key, so uniqueness is
(organization_id, template_key) rather than template_key alone.

The fork columns are stored on the draft rather than re-derived at publish, so
a Platform Template published between seeding and publishing cannot change the
baseline the author actually copied.

Publishing converts a draft into the next immutable agent_template row and
deletes the draft row (handled in service code, not this migration). No data
migration: existing organization lineages simply have no draft.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "87ec190e0f7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_template_draft",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("forked_from_platform_template_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("fork_baseline_platform_template_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("fork_baseline_platform_version", sa.Integer(), nullable=True),
        sa.Column("template_key", sa.String(length=255), nullable=False),
        sa.Column("template_name", sa.String(length=255), nullable=False),
        sa.Column("template_source", sa.String(length=20), nullable=False, server_default="custom"),
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
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["forked_from_platform_template_id"], ["platform_template.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["fork_baseline_platform_template_id"], ["platform_template.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("organization_id", "template_key", name="uq_agent_template_draft_org_key"),
        sa.Index("ix_agent_template_draft_organization_id", "organization_id"),
    )

    op.create_table(
        "agent_template_draft_skill",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draft_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_version", sa.Integer(), nullable=False),
        sa.Column("group_key", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["draft_id"], ["agent_template_draft.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["skill_id", "skill_version"],
            ["skill_version.skill_id", "skill_version.version"],
            ondelete="RESTRICT",
            name="fk_agent_template_draft_skill_version",
        ),
        sa.UniqueConstraint("draft_id", "skill_id", name="uq_agent_template_draft_skill"),
        sa.Index("ix_agent_template_draft_skill_draft", "draft_id"),
    )


def downgrade() -> None:
    op.drop_index("ix_agent_template_draft_skill_draft", table_name="agent_template_draft_skill")
    op.drop_table("agent_template_draft_skill")
    op.drop_index("ix_agent_template_draft_organization_id", table_name="agent_template_draft")
    op.drop_table("agent_template_draft")
