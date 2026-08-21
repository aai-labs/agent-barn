"""add_skill_draft_and_skill_draft_file_tables

Adds the draft/publish editing flow for skills: a ``skill_draft`` row (at most one
per lineage) holds an in-progress set of file edits until explicitly published,
mirroring ``PlatformTemplateDraft``. No backfill needed; every lineage starts with
no draft.

Revision ID: e2b6d9f1a4c7
Revises: c7d1e9f4a2b8
Create Date: 2026-08-13 09:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2b6d9f1a4c7"
down_revision: str | None = "c7d1e9f4a2b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skill_draft",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("skill_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_id", name="uq_skill_draft_skill_id"),
    )

    op.create_table(
        "skill_draft_file",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("skill_draft_id", sa.Uuid(), nullable=False),
        sa.Column("path", sa.String(length=512), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["skill_draft_id"], ["skill_draft.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("skill_draft_id", "path", name="uq_skill_draft_file_draft_path"),
    )
    op.create_index("ix_skill_draft_file_draft_id", "skill_draft_file", ["skill_draft_id"], unique=False)


def downgrade() -> None:
    op.drop_table("skill_draft_file")
    op.drop_table("skill_draft")
