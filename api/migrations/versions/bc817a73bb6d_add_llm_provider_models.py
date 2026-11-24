"""Add LLM provider models

Revision ID: bc817a73bb6d
Revises: 3f9f88255e3b
Create Date: 2026-11-18

`llm_provider_model` holds the models of each LLM Provider Connection, once per connection,
with their per-token prices. Input and output prices are above zero and cache prices zero or
more. A price taken from LiteLLM's price list keeps the key it was read under; a typed price
has none. The table starts empty.

The downgrade drops the table with every model in it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bc817a73bb6d"
down_revision: str | Sequence[str] | None = "3f9f88255e3b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "llm_provider_model"
_PRICE = sa.Numeric(24, 18)


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("input_cost_per_token", _PRICE, nullable=False),
        sa.Column("output_cost_per_token", _PRICE, nullable=False),
        sa.Column("cache_read_input_token_cost", _PRICE, nullable=False),
        sa.Column("cache_creation_input_token_cost", _PRICE, nullable=False),
        sa.Column("price_source", sa.String(length=16), nullable=False),
        sa.Column("litellm_price_key", sa.String(length=256), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["connection_id"], ["llm_provider_connection.id"]),
        sa.UniqueConstraint("connection_id", "model_id", name="uq_llm_provider_model_connection_model"),
        sa.CheckConstraint("model_id ~ '^[A-Za-z0-9._:/-]+$'", name="ck_llm_provider_model_model_id_format"),
        sa.CheckConstraint("input_cost_per_token > 0", name="ck_llm_provider_model_input_price_positive"),
        sa.CheckConstraint("output_cost_per_token > 0", name="ck_llm_provider_model_output_price_positive"),
        sa.CheckConstraint(
            "cache_read_input_token_cost >= 0", name="ck_llm_provider_model_cache_read_price_not_negative"
        ),
        sa.CheckConstraint(
            "cache_creation_input_token_cost >= 0", name="ck_llm_provider_model_cache_creation_price_not_negative"
        ),
        sa.CheckConstraint("price_source IN ('litellm', 'manual')", name="ck_llm_provider_model_price_source_known"),
        sa.CheckConstraint(
            "(litellm_price_key IS NOT NULL) = (price_source = 'litellm')",
            name="ck_llm_provider_model_price_key_by_source",
        ),
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
