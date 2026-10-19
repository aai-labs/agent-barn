"""Merge Playbooks and Agent Barn Telegram link heads.

Revision ID: dc378bacdf04
Revises: 82d7f9074830, a78bcde4b918
Create Date: 2026-10-19 17:33:31.630649

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "dc378bacdf04"
down_revision: str | Sequence[str] | None = ("82d7f9074830", "a78bcde4b918")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
