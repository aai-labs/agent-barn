"""Name the connection of every Organization allowlist entry

Revision ID: e5c2a9d4b7f1
Revises: b3d81c5e9f42
Create Date: 2026-11-27

An allowlist entry becomes `<connection slug>/<model>`, so an Organization can allow the models
of any LLM Provider Connection (AF-484). Every entry stored so far is an OpenRouter id or glob,
so each is prefixed with `openrouter/`, unconditionally: OpenRouter ids can themselves start with
`openrouter/`. The downgrade strips one `openrouter/` and drops the entries of other connections,
which the earlier format cannot express.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5c2a9d4b7f1"
down_revision: str | Sequence[str] | None = "b3d81c5e9f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREFIX = "openrouter/"
_LISTED = "jsonb_typeof(allowed_models) = 'array' AND jsonb_array_length(allowed_models) > 0"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE organization SET allowed_models = ("
            " SELECT jsonb_agg(:prefix || entry ORDER BY position)"
            " FROM jsonb_array_elements_text(allowed_models) WITH ORDINALITY AS listed(entry, position)"
            f") WHERE {_LISTED}"
        ).bindparams(prefix=_PREFIX)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE organization SET allowed_models = COALESCE(("
            " SELECT jsonb_agg(substr(entry, length(:prefix) + 1) ORDER BY position)"
            " FROM jsonb_array_elements_text(allowed_models) WITH ORDINALITY AS listed(entry, position)"
            " WHERE left(entry, length(:prefix)) = :prefix"
            f"), '[]'::jsonb) WHERE {_LISTED}"
        ).bindparams(prefix=_PREFIX)
    )
