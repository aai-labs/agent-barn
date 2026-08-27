import importlib
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4


class _MigrationResult:
    def __init__(self, *, scalar=None, rows=()):
        self.scalar = scalar
        self.rows = rows

    def scalar_one(self):
        return self.scalar

    def mappings(self):
        return self.rows


def test_duplicate_legacy_credentials_use_a_compatibility_scope() -> None:
    migration = importlib.import_module("api.migrations.versions.6d3a9e4c2f71_add_communication_connections")
    first_agent_id = uuid4()
    second_agent_id = uuid4()
    organization_id = uuid4()
    rows = [
        {
            "agent_id": first_agent_id,
            "organization_id": organization_id,
            "bot_token_encrypted": "encrypted-token",
            "app_token_encrypted": "encrypted-app-token",
            "channel_ids": [],
            "dm_user_ids": [],
            "group_policy": "open",
            "dm_policy": "open",
            "verbose_mode": True,
        },
        {
            "agent_id": second_agent_id,
            "organization_id": organization_id,
            "bot_token_encrypted": "encrypted-token",
            "app_token_encrypted": "encrypted-app-token",
            "channel_ids": [],
            "dm_user_ids": [],
            "group_policy": "open",
            "dm_policy": "open",
            "verbose_mode": True,
        },
    ]

    def execute(statement):
        sql = str(statement)
        if "SELECT count(*)" in sql:
            return _MigrationResult(scalar=2)
        if "agent_slack_config" in sql:
            return _MigrationResult(rows=rows)
        return _MigrationResult(rows=[])

    bind = SimpleNamespace(execute=Mock(side_effect=execute))
    insert_connection = Mock(side_effect=[uuid4(), uuid4()])
    with (
        patch.object(migration.op, "get_bind", return_value=bind),
        patch.object(
            migration,
            "get_config",
            return_value=SimpleNamespace(agent_token_encryption_key="migration-key"),
        ),
        patch.object(migration, "decrypt_token", side_effect=["same-token", "same-app", "same-token", "same-app"]),
        patch.object(migration, "_insert_connection", insert_connection),
    ):
        migration._backfill_connections()

    calls = insert_connection.call_args_list
    assert calls[0].kwargs["credential_scope_key"] == "global"
    assert calls[1].kwargs["credential_scope_key"] == f"legacy-agent:{second_agent_id}"


def test_discord_configuration_is_backfilled_into_plugin_connection() -> None:
    migration = importlib.import_module("api.migrations.versions.6d3a9e4c2f71_add_communication_connections")
    agent_id = uuid4()
    organization_id = uuid4()
    connection_id = uuid4()
    discord_row = {
        "agent_id": agent_id,
        "organization_id": organization_id,
        "bot_token_encrypted": "encrypted-discord-token",
        "guild_ids": ["guild-one"],
        "allowed_channel_ids": ["channel-one"],
        "allowed_user_ids": ["user-one"],
        "allowed_role_ids": ["role-one"],
        "home_channel_id": "channel-one",
        "require_mention": True,
        "group_policy": "allowlist",
    }

    def execute(statement):
        sql = str(statement)
        if "SELECT count(*)" in sql:
            return _MigrationResult(scalar=1)
        if "agent_discord_config" in sql:
            return _MigrationResult(rows=[discord_row])
        return _MigrationResult(rows=[])

    bind = SimpleNamespace(execute=Mock(side_effect=execute))
    insert_connection = Mock(return_value=connection_id)
    with (
        patch.object(migration.op, "get_bind", return_value=bind),
        patch.object(
            migration,
            "get_config",
            return_value=SimpleNamespace(agent_token_encryption_key="migration-key"),
        ),
        patch.object(migration, "decrypt_token", return_value="discord-token"),
        patch.object(migration, "_insert_connection", insert_connection),
    ):
        connection_by_agent = migration._backfill_connections()

    assert connection_by_agent == {agent_id: connection_id}
    insert_connection.assert_called_once_with(
        bind,
        agent_id=agent_id,
        organization_id=organization_id,
        platform_key="discord",
        display_name="Discord",
        settings={
            "guild_ids": ["guild-one"],
            "allowed_channel_ids": ["channel-one"],
            "allowed_user_ids": ["user-one"],
            "allowed_role_ids": ["role-one"],
            "home_channel_id": "channel-one",
            "require_mention": True,
            "group_policy": "allowlist",
            "dm_policy": "off",
        },
        credentials={"bot_token": "discord-token"},
        fingerprint_material="discord-token",
        external_identity=None,
        encryption_key="migration-key",
        credential_scope_key="global",
    )
