import json
import time
from dataclasses import dataclass
from unittest.mock import patch
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from pydantic import ValidationError

from api.domains.communications.models import PlatformCapability
from api.domains.communications.plugins.discord import DiscordPlatformPlugin
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.plugins.slack import SlackPlatformPlugin
from api.domains.communications.plugins.teams import TeamsPlatformPlugin
from api.domains.communications.plugins.telegram import TelegramPlatformPlugin


@dataclass
class ValidationConfig:
    skip_discord_token_validation: bool = True
    skip_slack_token_validation: bool = True
    skip_telegram_token_validation: bool = True


def test_registry_lists_shipped_plugins_in_stable_order() -> None:
    config = ValidationConfig()
    registry = PlatformPluginRegistry(
        [
            TelegramPlatformPlugin(config),
            DiscordPlatformPlugin(config),
            SlackPlatformPlugin(config),
            TeamsPlatformPlugin(),
        ]
    )

    assert [descriptor.key for descriptor in registry.descriptors()] == ["discord", "slack", "teams", "telegram"]
    assert PlatformCapability.DIRECTORY_DISCOVERY in registry.require("slack").descriptor.capabilities


def test_registry_rejects_duplicate_platform_keys() -> None:
    with pytest.raises(ValueError, match="Duplicate Platform Plugin key: teams"):
        PlatformPluginRegistry([TeamsPlatformPlugin(), TeamsPlatformPlugin()])


def test_slack_plugin_validates_and_fingerprints_only_the_bot_identity() -> None:
    config = ValidationConfig()
    plugin = SlackPlatformPlugin(config)
    organization_id = uuid4()
    agent_id = uuid4()

    first = plugin.validate_configuration(
        {"group_policy": "allowlist", "dm_policy": "off"},
        {"bot_token": "xoxb-one", "app_token": "xapp-one"},
        organization_id=organization_id,
        agent_id=agent_id,
    )
    rotated_app_token = plugin.validate_configuration(
        {"group_policy": "allowlist", "dm_policy": "off"},
        {"bot_token": "xoxb-one", "app_token": "xapp-two"},
        organization_id=organization_id,
        agent_id=agent_id,
    )

    assert first.credential_fingerprint == rotated_app_token.credential_fingerprint
    assert first.credential_scope_key == "global"
    assert first.external_identity == "validation-skipped"


def test_teams_plugin_rejects_unknown_settings() -> None:
    plugin = TeamsPlatformPlugin()

    with pytest.raises(ValidationError):
        plugin.validate_configuration(
            {"tenant_id": "tenant", "unexpected": True},
            {"app_id": "app", "app_password": "secret"},
            organization_id=uuid4(),
            agent_id=uuid4(),
        )


def test_telegram_plugin_returns_safe_external_identity_when_validation_is_skipped() -> None:
    config = ValidationConfig()
    plugin = TelegramPlatformPlugin(config)

    validated = plugin.validate_configuration(
        {},
        {"bot_token": "123:token"},
        organization_id=uuid4(),
        agent_id=uuid4(),
    )

    assert validated.external_identity == "validation-skipped"
    assert validated.credentials == {"bot_token": "123:token"}


def test_discord_plugin_normalizes_an_allowed_message_create_event() -> None:
    config = ValidationConfig()
    plugin = DiscordPlatformPlugin(config)
    settings = plugin.settings_model.model_validate(
        {
            "guild_ids": ["guild-1"],
            "allowed_channel_ids": ["channel-1"],
            "require_mention": True,
        }
    )

    envelopes = plugin.normalize_inbound(
        settings,
        {
            "t": "MESSAGE_CREATE",
            "agentbarn_bot_user_id": "bot-1",
            "d": {
                "id": "message-1",
                "guild_id": "guild-1",
                "channel_id": "channel-1",
                "timestamp": "2026-08-22T10:00:00+00:00",
                "content": "hello",
                "author": {"id": "user-1", "username": "Ada", "bot": False},
                "member": {"roles": []},
                "mentions": [{"id": "bot-1"}],
            },
        },
    )

    assert len(envelopes) == 1
    assert envelopes[0].provider_message_id == "message-1"
    assert envelopes[0].location.id == "channel-1"
    assert envelopes[0].sender.display_name == "Ada"


def test_discord_plugin_ignores_unmentioned_group_messages() -> None:
    plugin = DiscordPlatformPlugin(ValidationConfig())
    settings = plugin.settings_model.model_validate({"guild_ids": ["guild-1"]})

    assert (
        plugin.normalize_inbound(
            settings,
            {
                "t": "MESSAGE_CREATE",
                "agentbarn_bot_user_id": "bot-1",
                "d": {
                    "id": "message-1",
                    "guild_id": "guild-1",
                    "channel_id": "channel-1",
                    "author": {"id": "user-1", "bot": False},
                    "mentions": [],
                },
            },
        )
        == []
    )


def test_teams_plugin_authenticates_bot_connector_webhook() -> None:
    plugin = TeamsPlatformPlugin()
    credentials = plugin.credentials_model.model_validate({"app_id": "app-1", "app_password": "secret"})
    payload = {
        "type": "message",
        "channelId": "msteams",
        "serviceUrl": "https://smba.trafficmanager.net/teams",
    }
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_data = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    key_data.update({"kid": "key-1", "endorsements": ["msteams"]})
    now = int(time.time())
    token = jwt.encode(
        {
            "aud": "app-1",
            "iss": "https://api.botframework.com",
            "serviceUrl": payload["serviceUrl"],
            "nbf": now - 1,
            "exp": now + 60,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "key-1"},
    )

    with patch("api.domains.communications.plugins.teams._bot_connector_keys", return_value=[key_data]):
        plugin.verify_webhook(credentials, payload, f"Bearer {token}")


def test_teams_plugin_rejects_service_url_not_bound_by_token() -> None:
    plugin = TeamsPlatformPlugin()
    credentials = plugin.credentials_model.model_validate({"app_id": "app-1", "app_password": "secret"})
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key_data = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    key_data.update({"kid": "key-1", "endorsements": ["msteams"]})
    now = int(time.time())
    token = jwt.encode(
        {
            "aud": "app-1",
            "iss": "https://api.botframework.com",
            "serviceUrl": "https://trusted.example",
            "exp": now + 60,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "key-1"},
    )

    with (
        patch("api.domains.communications.plugins.teams._bot_connector_keys", return_value=[key_data]),
        pytest.raises(PermissionError, match="service URL"),
    ):
        plugin.verify_webhook(
            credentials,
            {"channelId": "msteams", "serviceUrl": "https://attacker.example"},
            f"Bearer {token}",
        )
