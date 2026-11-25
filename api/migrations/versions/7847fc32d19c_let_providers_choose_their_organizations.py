"""Let LLM providers choose their Organizations

Revision ID: 7847fc32d19c
Revises: 9a64534a1a2f
Create Date: 2026-11-24

`llm_provider_connection.organization_access` says which Organizations a connection is open
to: `all`, `none`, `all_except` the listed ones or `only` the listed ones. The listed
Organizations are in `llm_provider_connection_organization`, which loses its rows when their
connection or Organization is deleted. Every existing connection, OpenRouter included, is
open to all Organizations, as before, and lists none.

The downgrade drops the mode and every listed Organization.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7847fc32d19c"
down_revision: str | Sequence[str] | None = "9a64534a1a2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "llm_provider_connection"
_ACCESS_TABLE = "llm_provider_connection_organization"
_ACCESS_KNOWN = "ck_llm_provider_connection_organization_access_known"
_ORGANIZATION_INDEX = "ix_llm_provider_connection_organization_organization_id"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("organization_access", sa.String(length=16), nullable=False, server_default="all"))
    op.create_check_constraint(_ACCESS_KNOWN, _TABLE, "organization_access IN ('all', 'none', 'all_except', 'only')")
    op.create_table(
        _ACCESS_TABLE,
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["connection_id"], [f"{_TABLE}.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("connection_id", "organization_id"),
    )
    op.create_index(_ORGANIZATION_INDEX, _ACCESS_TABLE, ["organization_id"])


def downgrade() -> None:
    op.drop_index(_ORGANIZATION_INDEX, table_name=_ACCESS_TABLE)
    op.drop_table(_ACCESS_TABLE)
    op.drop_constraint(_ACCESS_KNOWN, _TABLE, type_="check")
    op.drop_column(_TABLE, "organization_access")
