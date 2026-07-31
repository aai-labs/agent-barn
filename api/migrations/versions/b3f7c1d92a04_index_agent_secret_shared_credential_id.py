"""index agent_secret.shared_credential_id

Postgres does not index the referencing side of a foreign key. Without this
index every reference count scans agent_secret, and every DELETE on
shared_credential scans it again to enforce the RESTRICT constraint.

Revision ID: b3f7c1d92a04
Revises: dee13d2cd664
Create Date: 2026-07-31 10:14:22.881034

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b3f7c1d92a04"
down_revision: Union[str, None] = "dee13d2cd664"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_agent_secret_shared_credential_id",
        "agent_secret",
        ["shared_credential_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_secret_shared_credential_id", table_name="agent_secret")
