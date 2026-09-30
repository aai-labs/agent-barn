"""add draft metadata (description, required_providers)

Revision ID: a1b2c3d4e6f7
Revises: 5f6e7d8c9b0a
Create Date: 2026-08-15 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e6f7"
down_revision: str | None = "5f6e7d8c9b0a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Draft metadata: description and required_providers are staged on the draft
    # and only applied to the skill row on publish, so the published version's
    # metadata stays frozen until a draft is published.
    op.add_column("skill_draft", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "skill_draft",
        sa.Column("required_providers", sa.JSON(), nullable=True),
    )
    # Backfill existing drafts from their skill row so in-flight drafts keep
    # the metadata they were created with.
    op.execute(
        """
        UPDATE skill_draft AS d
        SET description = s.description,
            required_providers = s.required_providers
        FROM skill AS s
        WHERE s.id = d.skill_id
        """
    )
    op.alter_column("skill_draft", "required_providers", existing_type=sa.JSON(), nullable=False)


def downgrade() -> None:
    op.drop_column("skill_draft", "required_providers")
    op.drop_column("skill_draft", "description")
