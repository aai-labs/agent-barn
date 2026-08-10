"""add platform_template_draft

Revision ID: 1d191f9ef700
Revises: 96333a5d58e4
Create Date: 2026-08-03 00:00:00.000000

Adds the Draft Template Version concept: an unpublished, in-progress next
version of a Platform Template lineage, authored only by a Platform
Administrator (see docs/adr/2026-08-03-platform-template-file-based-bootstrap.md
and CONTEXT.md). Unversioned and mutated in place while drafting; the unique
constraint on template_slug enforces at most one draft per lineage. Publishing
converts a draft into the next immutable platform_template row (handled in
service code, not this migration) and deletes the draft row.

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1d191f9ef700"
down_revision: str | Sequence[str] | None = "96333a5d58e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_template_draft",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("template_slug", sa.String(length=255), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_slug", name="uq_platform_template_draft_slug"),
    )

    op.create_table(
        "platform_template_draft_skill",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draft_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("group_key", sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["draft_id"], ["platform_template_draft.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("draft_id", "skill_id", name="uq_platform_template_draft_skill"),
        sa.Index("ix_platform_template_draft_skill_draft", "draft_id"),
    )


def downgrade() -> None:
    op.drop_index("ix_platform_template_draft_skill_draft", table_name="platform_template_draft_skill")
    op.drop_table("platform_template_draft_skill")
    op.drop_table("platform_template_draft")
