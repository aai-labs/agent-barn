"""rename template lineage slugs to opaque template keys

Revision ID: a3c4e5f6b7d8
Revises: 01a32822566b
Create Date: 2026-08-04 00:00:00.000000

The identifier values are intentionally preserved. Existing agent pins point to
stable template row UUIDs, so renaming these columns must not rewrite lineage
keys or repoint agents and forks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3c4e5f6b7d8"
down_revision: str | Sequence[str] | None = "01a32822566b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("agent_template", "platform_template", "platform_template_draft")


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(table, "template_slug", new_column_name="template_key")

    op.execute(
        sa.text(
            "ALTER TABLE agent_template "
            "RENAME CONSTRAINT uq_agent_template_org_slug_version "
            "TO uq_agent_template_org_key_version"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE platform_template "
            "RENAME CONSTRAINT uq_platform_template_slug_version "
            "TO uq_platform_template_key_version"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE platform_template_draft "
            "RENAME CONSTRAINT uq_platform_template_draft_slug "
            "TO uq_platform_template_draft_key"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE platform_template_draft "
            "RENAME CONSTRAINT uq_platform_template_draft_key "
            "TO uq_platform_template_draft_slug"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE platform_template "
            "RENAME CONSTRAINT uq_platform_template_key_version "
            "TO uq_platform_template_slug_version"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE agent_template "
            "RENAME CONSTRAINT uq_agent_template_org_key_version "
            "TO uq_agent_template_org_slug_version"
        )
    )

    for table in _TABLES:
        op.alter_column(table, "template_key", new_column_name="template_slug")
