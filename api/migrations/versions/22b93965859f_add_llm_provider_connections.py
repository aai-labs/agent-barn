"""Add LLM Provider Connections, seeded with OpenRouter

Revision ID: 22b93965859f
Revises: 38de1199ae19
Create Date: 2026-11-16

`llm_provider_connection` holds the provider accounts Agents reach models through, each with
an optional Fernet-encrypted key, its last four characters, and where the key came from. One
row is seeded: the `openrouter` connection, with no key. A slug stays unique among deleted
connections too, so it is never reused.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "22b93965859f"
down_revision: str | Sequence[str] | None = "38de1199ae19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "llm_provider_connection"
# Frozen here rather than imported: a migration must keep meaning what it meant when
# it shipped, whatever the code says later.
_OPENROUTER_ID = "00000000-0000-7000-8000-00000000a4e0"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("slug", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("api_key_encrypted", sa.String(), nullable=True),
        sa.Column("api_key_last4", sa.String(length=4), nullable=True),
        sa.Column("key_source", sa.String(length=16), nullable=True),
        sa.Column("updated_by", sa.Uuid(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_llm_provider_connection_slug_format"),
        sa.CheckConstraint("provider_type IN ('openrouter')", name="ck_llm_provider_connection_provider_type_known"),
        sa.CheckConstraint(
            "key_source IN ('environment', 'admin')", name="ck_llm_provider_connection_key_source_known"
        ),
        sa.CheckConstraint(
            "(api_key_encrypted IS NULL) = (api_key_last4 IS NULL)"
            " AND (api_key_encrypted IS NULL) = (key_source IS NULL)",
            name="ck_llm_provider_connection_key_complete",
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.execute(
        sa.text(
            f"INSERT INTO {_TABLE} (id, created_at, updated_at, slug, name, provider_type)"
            " VALUES (:id, now(), now(), 'openrouter', 'OpenRouter', 'openrouter')"
        ).bindparams(id=_OPENROUTER_ID)
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
