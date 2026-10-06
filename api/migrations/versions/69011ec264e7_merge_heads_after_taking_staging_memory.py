"""merge heads after taking staging memory

Staging added the agent memory settings and key revocation tables while AF-170's platform
capacity limits were in review. Neither touches the other's tables.

Revision ID: 69011ec264e7
Revises: 821ed7cce78f, f03a9c61d872
Create Date: 2026-10-06

"""

from collections.abc import Sequence

revision: str = "69011ec264e7"
down_revision: str | Sequence[str] | None = ("821ed7cce78f", "f03a9c61d872")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
