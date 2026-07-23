"""Switch password_reset_token from a JWT jti to an opaque token hash.

Invites and password resets now use an opaque random token; only its SHA-256 hash is
stored. Existing (JWT-based) rows are stale after this migration and are cleared so no
half-migrated tokens linger — affected users simply request a fresh link.

Revision ID: d3f9a1c7b2e5
Revises: ab2b4bb88c6f
"""

from typing import Union

from alembic import op

revision: str = "d3f9a1c7b2e5"
down_revision: Union[str, None] = "ab2b4bb88c6f"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # Old JWT-jti rows can't map to the new opaque-hash scheme; drop them.
    op.execute("DELETE FROM password_reset_token")
    op.alter_column("password_reset_token", "jti", new_column_name="token_hash")
    op.create_index(
        "ix_password_reset_token_token_hash",
        "password_reset_token",
        ["token_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_password_reset_token_token_hash", table_name="password_reset_token")
    op.alter_column("password_reset_token", "token_hash", new_column_name="jti")
