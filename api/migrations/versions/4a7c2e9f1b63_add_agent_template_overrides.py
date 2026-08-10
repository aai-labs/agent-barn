"""add Agent-owned Template Override drafts and versions

Revision ID: 4a7c2e9f1b63
Revises: 3df7fef61316
Create Date: 2026-08-09 00:00:00.000000

Agent Template Overrides are private, immutable configuration snapshots. The
source ids are nullable because a self-contained historical snapshot remains
valid after its original shared source is removed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a7c2e9f1b63"
down_revision: str | Sequence[str] | None = "3df7fef61316"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _snapshot_columns() -> list[sa.Column]:
    return [
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_template_key", sa.String(length=255), nullable=False),
        sa.Column("source_template_version", sa.Integer(), nullable=False),
        sa.Column("source_platform_template_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("source_agent_template_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("template_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("soul_md", sa.Text(), nullable=False),
        sa.Column("identity_md", sa.Text(), nullable=False),
        sa.Column("user_md", sa.Text(), nullable=False),
        sa.Column("tools_md", sa.Text(), nullable=False),
        sa.Column("agents_md", sa.Text(), nullable=False),
        sa.Column("boot_md", sa.Text(), nullable=False),
        sa.Column("bootstrap_md", sa.Text(), nullable=False),
        sa.Column("heartbeat_md", sa.Text(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "agent_template_override_draft",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(as_uuid=True), nullable=True),
        *_snapshot_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_template_override_draft_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_platform_template_id"], ["platform_template.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_agent_template_id"], ["agent_template.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("agent_id", name="uq_agent_template_override_draft_agent"),
        sa.Index("ix_agent_template_override_draft_organization", "organization_id"),
    )

    op.create_table(
        "agent_template_override_version",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(as_uuid=True), nullable=True),
        *_snapshot_columns(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_agent_template_override_version_agent_organization",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_platform_template_id"], ["platform_template.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_agent_template_id"], ["agent_template.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("agent_id", "version", name="uq_agent_template_override_version_agent_version"),
        sa.Index("ix_agent_template_override_version_organization", "organization_id"),
        sa.Index("ix_agent_template_override_version_agent", "agent_id"),
    )

    op.create_table(
        "agent_template_override_draft_skill",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draft_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("group_key", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["draft_id"],
            ["agent_template_override_draft.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("draft_id", "skill_id", name="uq_agent_template_override_draft_skill"),
        sa.Index("ix_agent_template_override_draft_skill_draft", "draft_id"),
    )

    op.create_table(
        "agent_template_override_version_skill",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("group_key", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["agent_template_override_version.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("version_id", "skill_id", name="uq_agent_template_override_version_skill"),
        sa.Index("ix_agent_template_override_version_skill_version", "version_id"),
    )

    op.drop_constraint("ck_agent_template_pin_state", "agent", type_="check")
    op.add_column(
        "agent",
        sa.Column("agent_template_override_version_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_agent_template_override_version_pin",
        "agent",
        "agent_template_override_version",
        ["agent_template_override_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_agent_template_pin_state",
        "agent",
        "deleted_at IS NOT NULL OR ((platform_template_id IS NOT NULL)::integer "
        "+ (agent_template_id IS NOT NULL)::integer "
        "+ (agent_template_override_version_id IS NOT NULL)::integer = 1)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_agent_template_pin_state", "agent", type_="check")
    op.drop_constraint("fk_agent_template_override_version_pin", "agent", type_="foreignkey")
    op.drop_column("agent", "agent_template_override_version_id")
    op.create_check_constraint(
        "ck_agent_template_pin_state",
        "agent",
        "deleted_at IS NOT NULL OR ((platform_template_id IS NOT NULL)::integer "
        "+ (agent_template_id IS NOT NULL)::integer = 1)",
    )

    op.drop_index(
        "ix_agent_template_override_version_skill_version",
        table_name="agent_template_override_version_skill",
    )
    op.drop_table("agent_template_override_version_skill")
    op.drop_index(
        "ix_agent_template_override_draft_skill_draft",
        table_name="agent_template_override_draft_skill",
    )
    op.drop_table("agent_template_override_draft_skill")
    op.drop_index("ix_agent_template_override_version_agent", table_name="agent_template_override_version")
    op.drop_index(
        "ix_agent_template_override_version_organization",
        table_name="agent_template_override_version",
    )
    op.drop_table("agent_template_override_version")
    op.drop_index(
        "ix_agent_template_override_draft_organization",
        table_name="agent_template_override_draft",
    )
    op.drop_table("agent_template_override_draft")
