"""add ingest_key_encrypted to agent

Revision ID: e9cad4733449
Revises: f1a2b3c4d5e6
Create Date: 2026-06-26 13:28:39.245115

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9cad4733449"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("ingest_key_encrypted", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent", "ingest_key_encrypted")
