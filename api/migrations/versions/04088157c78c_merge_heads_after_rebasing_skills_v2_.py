"""merge heads after rebasing skills-v2 onto staging

Revision ID: 04088157c78c
Revises: a1b2c3d4e6f7, d5e2a9f4c781
Create Date: 2026-08-17 12:29:22.999052

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "04088157c78c"
down_revision: str | Sequence[str] | None = ("a1b2c3d4e6f7", "d5e2a9f4c781")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
