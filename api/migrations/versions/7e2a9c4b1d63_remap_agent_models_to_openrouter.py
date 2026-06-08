"""remap agent models to openrouter slugs

Switches stored agent model strings from the old short-name format
(litellm/<name>) to the wildcard-passthrough format (litellm/openrouter/<slug>).
The old short names only resolved because the LiteLLM config carried named
model_list entries; those are dropped in favour of an openrouter/* wildcard,
so existing rows must be rewritten to the full OpenRouter slug.

Revision ID: 7e2a9c4b1d63
Revises: 0dfb8ab409db
Create Date: 2026-06-07

"""

from typing import Sequence, Union

from alembic import op

revision: str = "7e2a9c4b1d63"
down_revision: Union[str, None] = "0dfb8ab409db"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# old short-name model string -> new openrouter-slug model string
_REMAP = {
    "litellm/qwen3.6-plus": "litellm/openrouter/qwen/qwen3.6-plus",
    "litellm/gpt-5-mini": "litellm/openrouter/openai/gpt-5-mini",
}


def upgrade() -> None:
    for old, new in _REMAP.items():
        op.execute(f"UPDATE agent SET model = '{new}' WHERE model = '{old}'")


def downgrade() -> None:
    for old, new in _REMAP.items():
        op.execute(f"UPDATE agent SET model = '{old}' WHERE model = '{new}'")
