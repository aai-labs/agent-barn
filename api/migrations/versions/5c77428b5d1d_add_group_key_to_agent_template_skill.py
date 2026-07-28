"""add group_key to agent_template_skill

Rows on the same template sharing a non-NULL group_key form an "at least
one of" requirement group (e.g. GitHub OR Bitbucket). NULL means the skill
is a standalone AND-required skill, matching all pre-existing rows.

Revision ID: 5c77428b5d1d
Revises: ad8b4a278dd1
Create Date: 2026-07-28

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5c77428b5d1d"
down_revision: Union[str, None] = "ad8b4a278dd1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_template_skill", sa.Column("group_key", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_template_skill", "group_key")
