"""Add more LLM providers besides OpenRouter

Revision ID: 91ad0093c626
Revises: 22b93965859f
Create Date: 2026-11-17

`llm_provider_connection` accepts Anthropic, OpenAI, Gemini, xAI, DeepSeek, Fireworks,
Novita, Azure and Custom besides OpenRouter, and gains `base_url`. A known provider's slug
must be its provider type and it has no base URL. An Azure or Custom connection needs a base
URL, and its slug can't be any provider type. The OpenRouter row already fits, so no data
changes on upgrade.

The downgrade deletes every connection that is not OpenRouter, deleted ones included, with
their stored keys, then drops `base_url` and the checks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "91ad0093c626"
down_revision: str | Sequence[str] | None = "22b93965859f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "llm_provider_connection"
_ALL_TYPES = (
    "'openrouter', 'anthropic', 'openai', 'gemini', 'xai', 'deepseek', 'fireworks', 'novita', 'azure', 'custom'"
)
_BASE_URL_TYPES = "'azure', 'custom'"
_TYPE_KNOWN = "ck_llm_provider_connection_provider_type_known"
_NEW_CHECKS = {
    "ck_llm_provider_connection_base_url_by_type": f"(base_url IS NOT NULL) = (provider_type IN ({_BASE_URL_TYPES}))",
    "ck_llm_provider_connection_known_slug_is_type": f"provider_type IN ({_BASE_URL_TYPES}) OR slug = provider_type",
    "ck_llm_provider_connection_own_slug_not_a_type": (
        f"provider_type NOT IN ({_BASE_URL_TYPES}) OR slug NOT IN ({_ALL_TYPES})"
    ),
}


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("base_url", sa.String(length=2048), nullable=True))
    op.drop_constraint(_TYPE_KNOWN, _TABLE, type_="check")
    op.create_check_constraint(_TYPE_KNOWN, _TABLE, f"provider_type IN ({_ALL_TYPES})")
    for name, condition in _NEW_CHECKS.items():
        op.create_check_constraint(name, _TABLE, condition)


def downgrade() -> None:
    op.execute(sa.text(f"DELETE FROM {_TABLE} WHERE provider_type <> 'openrouter'"))
    for name in _NEW_CHECKS:
        op.drop_constraint(name, _TABLE, type_="check")
    op.drop_constraint(_TYPE_KNOWN, _TABLE, type_="check")
    op.create_check_constraint(_TYPE_KNOWN, _TABLE, "provider_type IN ('openrouter')")
    op.drop_column(_TABLE, "base_url")
