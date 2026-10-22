"""Merge credit top-ups, playbooks and Gmail app password heads.

Revision ID: effd26cf62fa
Revises: e03b958c55bf, dc378bacdf04, 8e5c1f3a9b27
Create Date: 2026-10-20 09:28:41.075539

Staging carries two heads of its own (playbooks and the Gmail app password both
follow a78bcde4b918), so this joins them along with the credit top-ups head.

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "effd26cf62fa"
down_revision: str | Sequence[str] | None = ("e03b958c55bf", "dc378bacdf04", "8e5c1f3a9b27")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
