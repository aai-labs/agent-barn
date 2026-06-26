"""add ingest_key_encrypted to agent

Revision ID: e9cad4733449
Revises: 032ff9a474bb
Create Date: 2026-06-26 13:28:39.245115

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9cad4733449'
down_revision: Union[str, None] = '032ff9a474bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent", sa.Column("ingest_key_encrypted", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("agent", "ingest_key_encrypted")
