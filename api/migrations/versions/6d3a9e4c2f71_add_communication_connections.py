"""add communication connections

Revision ID: 6d3a9e4c2f71
Revises: 04088157c78c
Create Date: 2026-08-22 11:15:00.000000

"""

import hashlib
import json
import secrets
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from api.core.config import get_config
from api.infrastructure.crypto import decrypt_token, encrypt_token

revision: str = "6d3a9e4c2f71"
down_revision: str | Sequence[str] | None = "04088157c78c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


connection_status = sa.Enum(
    "PENDING",
    "CONNECTING",
    "CONNECTED",
    "DEGRADED",
    "ERROR",
    name="connectionobservedstatus",
)


def _encrypted_json(payload: dict[str, str], key: str) -> str:
    return encrypt_token(json.dumps(payload, sort_keys=True, separators=(",", ":")), key)


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _insert_connection(
    bind,
    *,
    agent_id,
    organization_id,
    platform_key: str,
    display_name: str,
    settings: dict,
    credentials: dict[str, str],
    fingerprint_material: str,
    external_identity: str | None,
    encryption_key: str,
) -> uuid.UUID:
    connection_id = uuid.uuid4()
    bind.execute(
        sa.text(
            """
            INSERT INTO communication_connection (
                id, created_at, updated_at, organization_id, agent_id,
                platform_key, display_name, enabled, schema_version, settings,
                credentials_encrypted, driver_key_encrypted, external_identity, credential_fingerprint,
                credential_scope_key, observed_status, revision
            ) VALUES (
                :id, now(), now(), :organization_id, :agent_id,
                :platform_key, :display_name, true, 1, CAST(:settings AS json),
                :credentials_encrypted, :driver_key_encrypted, :external_identity, :credential_fingerprint,
                'global', 'PENDING', 1
            )
            """
        ),
        {
            "id": connection_id,
            "organization_id": organization_id,
            "agent_id": agent_id,
            "platform_key": platform_key,
            "display_name": display_name,
            "settings": json.dumps(settings),
            "credentials_encrypted": _encrypted_json(credentials, encryption_key),
            "driver_key_encrypted": encrypt_token(secrets.token_urlsafe(32), encryption_key),
            "external_identity": external_identity,
            "credential_fingerprint": _fingerprint(fingerprint_material),
        },
    )
    return connection_id


def _backfill_connections() -> dict[uuid.UUID, uuid.UUID]:
    bind = op.get_bind()
    config_count = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM agent_slack_config) + "
            "(SELECT count(*) FROM agent_teams_config) + "
            "(SELECT count(*) FROM agent_telegram_config) + "
            "(SELECT count(*) FROM agent_discord_config)"
        )
    ).scalar_one()
    if not config_count:
        return {}
    encryption_key = get_config().agent_token_encryption_key
    if not encryption_key:
        raise RuntimeError("AGENT_TOKEN_ENCRYPTION_KEY is required to migrate Communication Connections")

    connection_by_agent: dict[uuid.UUID, uuid.UUID] = {}
    slack_rows = bind.execute(
        sa.text(
            """
            SELECT a.id AS agent_id, a.organization_id, c.bot_token_encrypted,
                   c.app_token_encrypted, c.channel_ids, c.dm_user_ids,
                   c.group_policy, c.dm_policy, c.verbose_mode
            FROM agent a
            JOIN agent_slack_config c ON c.agent_id = a.id
            WHERE a.platform = 'slack'
            """
        )
    ).mappings()
    for row in slack_rows:
        bot_token = decrypt_token(row["bot_token_encrypted"], encryption_key)
        app_token = decrypt_token(row["app_token_encrypted"], encryption_key)
        connection_by_agent[row["agent_id"]] = _insert_connection(
            bind,
            agent_id=row["agent_id"],
            organization_id=row["organization_id"],
            platform_key="slack",
            display_name="Slack",
            settings={
                "channel_ids": row["channel_ids"] or [],
                "dm_user_ids": row["dm_user_ids"] or [],
                "group_policy": row["group_policy"],
                "dm_policy": row["dm_policy"],
                "verbose_mode": row["verbose_mode"],
            },
            credentials={"bot_token": bot_token, "app_token": app_token},
            fingerprint_material=bot_token,
            external_identity=None,
            encryption_key=encryption_key,
        )

    teams_rows = bind.execute(
        sa.text(
            """
            SELECT a.id AS agent_id, a.organization_id, c.app_id_encrypted,
                   c.app_password_encrypted, c.tenant_id
            FROM agent a
            JOIN agent_teams_config c ON c.agent_id = a.id
            WHERE a.platform = 'teams'
            """
        )
    ).mappings()
    for row in teams_rows:
        app_id = decrypt_token(row["app_id_encrypted"], encryption_key)
        app_password = decrypt_token(row["app_password_encrypted"], encryption_key)
        connection_by_agent[row["agent_id"]] = _insert_connection(
            bind,
            agent_id=row["agent_id"],
            organization_id=row["organization_id"],
            platform_key="teams",
            display_name="Microsoft Teams",
            settings={"tenant_id": row["tenant_id"]},
            credentials={"app_id": app_id, "app_password": app_password},
            fingerprint_material=app_id,
            external_identity=f"{row['tenant_id']} / {app_id}",
            encryption_key=encryption_key,
        )

    telegram_rows = bind.execute(
        sa.text(
            """
            SELECT a.id AS agent_id, a.organization_id, c.bot_token_encrypted,
                   c.bot_username, c.allowed_user_ids, c.allowed_chat_ids,
                   c.group_policy, c.dm_policy
            FROM agent a
            JOIN agent_telegram_config c ON c.agent_id = a.id
            WHERE a.platform = 'telegram'
            """
        )
    ).mappings()
    for row in telegram_rows:
        bot_token = decrypt_token(row["bot_token_encrypted"], encryption_key)
        connection_by_agent[row["agent_id"]] = _insert_connection(
            bind,
            agent_id=row["agent_id"],
            organization_id=row["organization_id"],
            platform_key="telegram",
            display_name="Telegram",
            settings={
                "allowed_user_ids": row["allowed_user_ids"] or [],
                "allowed_chat_ids": row["allowed_chat_ids"] or [],
                "group_policy": row["group_policy"],
                "dm_policy": row["dm_policy"],
            },
            credentials={"bot_token": bot_token},
            fingerprint_material=bot_token,
            external_identity=f"@{row['bot_username']}" if row["bot_username"] else None,
            encryption_key=encryption_key,
        )

    discord_rows = bind.execute(
        sa.text(
            """
            SELECT a.id AS agent_id, a.organization_id, c.bot_token_encrypted,
                   c.guild_ids, c.allowed_channel_ids, c.allowed_user_ids,
                   c.allowed_role_ids, c.home_channel_id, c.require_mention,
                   c.group_policy
            FROM agent a
            JOIN agent_discord_config c ON c.agent_id = a.id
            WHERE a.platform = 'discord'
            """
        )
    ).mappings()
    for row in discord_rows:
        bot_token = decrypt_token(row["bot_token_encrypted"], encryption_key)
        connection_by_agent[row["agent_id"]] = _insert_connection(
            bind,
            agent_id=row["agent_id"],
            organization_id=row["organization_id"],
            platform_key="discord",
            display_name="Discord",
            settings={
                "guild_ids": row["guild_ids"] or [],
                "allowed_channel_ids": row["allowed_channel_ids"] or [],
                "allowed_user_ids": row["allowed_user_ids"] or [],
                "allowed_role_ids": row["allowed_role_ids"] or [],
                "home_channel_id": row["home_channel_id"],
                "require_mention": row["require_mention"],
                "group_policy": row["group_policy"],
                "dm_policy": "off",
            },
            credentials={"bot_token": bot_token},
            fingerprint_material=bot_token,
            external_identity=None,
            encryption_key=encryption_key,
        )

    return connection_by_agent


def upgrade() -> None:
    op.create_table(
        "communication_connection",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("platform_key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("settings", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("credentials_encrypted", sa.Text(), nullable=False),
        sa.Column("driver_key_encrypted", sa.Text(), nullable=False),
        sa.Column("external_identity", sa.String(length=512), nullable=True),
        sa.Column("credential_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("credential_scope_key", sa.String(length=128), nullable=True),
        sa.Column("observed_status", connection_status, nullable=True),
        sa.Column("last_health_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=100), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.Column("ingress_lease_owner", sa.String(length=64), nullable=True),
        sa.Column("ingress_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("revision > 0", name="ck_communication_connection_revision"),
        sa.CheckConstraint("schema_version > 0", name="ck_communication_connection_schema_version"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"],
            ["agent.id", "agent.organization_id"],
            name="fk_communication_connection_agent_organization",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "organization_id", name="uq_communication_connection_id_organization"),
        sa.UniqueConstraint(
            "platform_key",
            "credential_scope_key",
            "credential_fingerprint",
            name="uq_communication_connection_credential",
        ),
    )
    op.create_index("ix_communication_connection_agent", "communication_connection", ["agent_id"])
    op.create_index(
        "ix_communication_connection_organization",
        "communication_connection",
        ["organization_id"],
    )
    op.create_index("ix_communication_connection_platform", "communication_connection", ["platform_key"])
    op.create_index(
        "uq_communication_connection_active_name",
        "communication_connection",
        ["agent_id", sa.text("lower(display_name)")],
        unique=True,
        postgresql_where=sa.text("retired_at IS NULL"),
    )

    connection_by_agent = _backfill_connections()
    op.add_column("agent_chat_message", sa.Column("connection_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_agent_chat_message_connection",
        "agent_chat_message",
        "communication_connection",
        ["connection_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    bind = op.get_bind()
    for agent_id, connection_id in connection_by_agent.items():
        bind.execute(
            sa.text("UPDATE agent_chat_message SET connection_id = :connection_id WHERE agent_id = :agent_id"),
            {"agent_id": agent_id, "connection_id": connection_id},
        )
    op.create_index(
        "ix_agent_chat_message_connection_channel",
        "agent_chat_message",
        ["connection_id", "channel_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_chat_message_connection_channel", table_name="agent_chat_message")
    op.drop_constraint("fk_agent_chat_message_connection", "agent_chat_message", type_="foreignkey")
    op.drop_column("agent_chat_message", "connection_id")
    op.drop_index("uq_communication_connection_active_name", table_name="communication_connection")
    op.drop_index("ix_communication_connection_platform", table_name="communication_connection")
    op.drop_index("ix_communication_connection_organization", table_name="communication_connection")
    op.drop_index("ix_communication_connection_agent", table_name="communication_connection")
    op.drop_table("communication_connection")
    connection_status.drop(op.get_bind(), checkfirst=True)
