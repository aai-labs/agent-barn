"""add group_key to platform_template_skill

Mirrors group_key on agent_template_skill (5c77428b5d1d) so global platform
predefined templates (e.g. PR Reviewer's GitHub-or-Bitbucket requirement) can
seed "at least one of" requirement groups too, now that predefined templates
live in platform_template/platform_template_skill instead of agent_template.

Revision ID: b4127aa08b89
Revises: 5c77428b5d1d
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4127aa08b89"
down_revision: str | None = "5c77428b5d1d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("platform_template_skill", sa.Column("group_key", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("platform_template_skill", "group_key")
