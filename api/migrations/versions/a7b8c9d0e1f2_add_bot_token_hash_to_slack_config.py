"""Add bot_token_hash to agent_slack_config for uniqueness enforcement.

Adds a SHA-256 hash column alongside the Fernet-encrypted bot token so duplicate
tokens can be detected at the database level. Existing rows are backfilled by
decrypting each token and computing its hash. A partial unique index prevents two
active agents from sharing the same Slack bot token.

Revision ID: a7b8c9d0e1f2
Revises: d3f9a1c7b2e5
"""

import hashlib
import logging
import os
from typing import Union

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "d3f9a1c7b2e5"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None

logger = logging.getLogger("alembic")


def upgrade() -> None:
    op.add_column(
        "agent_slack_config",
        sa.Column("bot_token_hash", sa.String(64), nullable=True),
    )

    key = os.environ.get("AGENT_TOKEN_ENCRYPTION_KEY", "")
    if not key:
        logger.warning(
            "AGENT_TOKEN_ENCRYPTION_KEY not set; skipping bot_token_hash backfill. "
            "Run this migration with the key set to populate hashes."
        )
    else:
        conn = op.get_bind()
        fernet = Fernet(key.encode())

        rows = conn.execute(
            sa.text(
                "SELECT sc.id, sc.bot_token_encrypted, a.deleted_at, a.name, a.created_at "
                "FROM agent_slack_config sc "
                "JOIN agent a ON a.id = sc.agent_id "
                "ORDER BY a.created_at ASC"
            )
        ).fetchall()

        seen_hashes: dict[str, str] = {}

        for row in rows:
            config_id = str(row[0])
            ciphertext = row[1]
            deleted_at = row[2]
            agent_name = row[3]

            if deleted_at is not None:
                continue

            try:
                plaintext = fernet.decrypt(ciphertext.encode()).decode()
            except Exception:
                logger.warning(
                    "Could not decrypt bot_token for config %s (agent '%s'); skipping",
                    config_id,
                    agent_name,
                )
                continue

            token_hash = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()

            if token_hash in seen_hashes:
                logger.warning(
                    "DATA INTEGRITY: agent '%s' (config %s) shares a Slack bot token "
                    "with an earlier agent. Setting its hash to NULL. "
                    "This agent needs its Slack bot token reconfigured.",
                    agent_name,
                    config_id,
                )
                continue

            seen_hashes[token_hash] = config_id
            conn.execute(
                sa.text(
                    "UPDATE agent_slack_config SET bot_token_hash = :hash WHERE id = :id"
                ),
                {"hash": token_hash, "id": config_id},
            )

    op.create_index(
        "ix_agent_slack_config_bot_token_hash",
        "agent_slack_config",
        ["bot_token_hash"],
        unique=True,
        postgresql_where=sa.text("bot_token_hash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_slack_config_bot_token_hash",
        table_name="agent_slack_config",
    )
    op.drop_column("agent_slack_config", "bot_token_hash")
