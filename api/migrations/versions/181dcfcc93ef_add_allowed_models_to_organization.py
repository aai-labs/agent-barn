"""Add allowed_models to organization

Revision ID: 181dcfcc93ef
Revises: 4934b7713177
Create Date: 2026-07-15 12:08:32.523789

"""

import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "181dcfcc93ef"
down_revision: Union[str, None] = "4934b7713177"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organization",
        sa.Column(
            "allowed_models",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=True,
        ),
    )

    # --- Backfill existing orgs ---
    from api.core.config import get_config

    raw_allowlist = get_config().agent_model_allowlist
    # Old semantics: an empty/unset allowlist meant "allow everything". The new
    # per-org allowlist treats empty as "block everything", so an empty config
    # must backfill to ["*"] rather than [] or every existing org loses access
    # to all models.
    allowed = [m.strip() for m in raw_allowlist.split(",") if m.strip()] if raw_allowlist else ["*"]

    op.execute(
        sa.text("UPDATE organization SET allowed_models = CAST(:models AS jsonb)").bindparams(
            sa.bindparam("models", value=json.dumps(allowed))
        )
    )


def downgrade() -> None:
    op.drop_column("organization", "allowed_models")
