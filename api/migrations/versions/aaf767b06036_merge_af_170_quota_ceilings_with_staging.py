"""Merge the AF-170 quota ceilings with staging's gateway retirement and personal API key histories.

Revision ID: aaf767b06036
Revises: 286b62f28057, fa6ffd5fe1f2
"""

from collections.abc import Sequence

revision: str = "aaf767b06036"
down_revision: str | Sequence[str] | None = ("286b62f28057", "fa6ffd5fe1f2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
