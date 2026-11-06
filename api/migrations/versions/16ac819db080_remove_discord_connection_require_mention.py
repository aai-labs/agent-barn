"""remove Discord Connection require mention

Revision ID: 16ac819db080
Revises: 00cdd18a6e91
Create Date: 2026-10-28 00:00:00.000000

No-op: Require @mention was kept. Later merges depend on this revision.
"""

revision: str = "16ac819db080"
down_revision: str | None = "00cdd18a6e91"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
