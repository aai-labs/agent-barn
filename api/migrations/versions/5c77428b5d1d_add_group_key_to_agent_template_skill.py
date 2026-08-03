"""add group_key to agent_template_skill

Rows on the same template sharing a non-NULL group_key form an "at least
one of" requirement group (e.g. GitHub OR Bitbucket). NULL means the skill
is a standalone AND-required skill, matching all pre-existing rows.

Revision ID: 5c77428b5d1d
Revises: b3f7c1d92a04
Create Date: 2026-07-28

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5c77428b5d1d"
down_revision: str | None = "b3f7c1d92a04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_template_skill", sa.Column("group_key", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_template_skill", "group_key")
