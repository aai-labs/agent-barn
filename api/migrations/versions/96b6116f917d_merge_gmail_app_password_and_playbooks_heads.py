"""Merge the Gmail app password head with the Playbooks and Telegram link merge head.

Revision ID: 96b6116f917d
Revises: 8e5c1f3a9b27, dc378bacdf04
Create Date: 2026-10-19 23:42:05.860621

Only 8e5c1f3a9b27 rebuilds ck_agent_secret_provider, from the most recent rebuild, so
joining the heads drops no provider and needs no schema change.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "96b6116f917d"
down_revision: str | Sequence[str] | None = ("8e5c1f3a9b27", "dc378bacdf04")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
