import re
from dataclasses import dataclass
from uuid import uuid4

import pytest
from pydantic import ValidationError

from api.domains.communications.models import CommunicationPlatform, PlatformCapability
from api.domains.communications.plugins.agentbarn_telegram import (
    AgentBarnTelegramPlatformPlugin,
    runtime_webhook_secret,
)
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.plugins.web import WebPlatformPlugin


@dataclass
class BotConfig:
    agentbarn_telegram_bot_token: str = "424242:agentbarn-test-bot-token"
    agentbarn_telegram_bot_username: str = "AgentBarnTestBot"


def test_agentbarn_telegram_is_its_own_platform_beside_bring_your_own_telegram() -> None:
    plugin = AgentBarnTelegramPlatformPlugin(BotConfig())

    assert plugin.key == CommunicationPlatform.AGENTBARN_TELEGRAM.value == "agentbarn_telegram"
    assert plugin.key != CommunicationPlatform.TELEGRAM.value
    assert plugin.display_name == "Agent Barn Telegram"


def test_agentbarn_telegram_asks_the_user_for_nothing() -> None:
    descriptor = AgentBarnTelegramPlatformPlugin(BotConfig()).descriptor

    assert descriptor.settings_schema.get("properties", {}) == {}
    assert descriptor.credentials_schema.get("properties", {}) == {}


def test_agentbarn_telegram_is_never_supervised_by_the_communications_gateway() -> None:
    # The runtime's own Telegram adapter carries this platform's traffic, so the
    # gateway must never poll it or create Communication Deliveries for it.
    plugin = AgentBarnTelegramPlatformPlugin(BotConfig())

    assert PlatformCapability.SUPERVISED_INGRESS not in plugin.capabilities
    assert PlatformCapability.WEBHOOK_INGRESS not in plugin.capabilities


def test_agentbarn_telegram_identifies_the_shared_bot_without_any_credential() -> None:
    plugin = AgentBarnTelegramPlatformPlugin(BotConfig())

    validated = plugin.validate_configuration({}, {}, organization_id=uuid4(), agent_id=uuid4())

    assert validated.external_identity == "@AgentBarnTestBot"
    assert validated.credentials == {}
    assert validated.credential_fingerprint is None
    assert validated.credential_scope_key is None


@pytest.mark.parametrize(
    ("settings", "credentials"),
    [({"dm_policy": "open"}, {}), ({}, {"bot_token": "123:token"})],
)
def test_agentbarn_telegram_rejects_any_settings_or_credentials(settings: dict, credentials: dict) -> None:
    plugin = AgentBarnTelegramPlatformPlugin(BotConfig())

    with pytest.raises(ValidationError):
        plugin.validate_configuration(settings, credentials, organization_id=uuid4(), agent_id=uuid4())


@pytest.mark.parametrize(
    ("token", "username", "offered"),
    [
        ("424242:agentbarn-test-bot-token", "AgentBarnTestBot", True),
        ("", "AgentBarnTestBot", False),
        ("424242:agentbarn-test-bot-token", "", False),
        ("  ", "@", False),
    ],
)
def test_agentbarn_telegram_is_offered_only_when_the_shared_bot_is_configured(
    token: str, username: str, offered: bool
) -> None:
    plugin = AgentBarnTelegramPlatformPlugin(
        BotConfig(agentbarn_telegram_bot_token=token, agentbarn_telegram_bot_username=username)
    )

    assert plugin.is_offered() is offered


def test_a_leading_at_sign_in_the_configured_username_is_not_doubled() -> None:
    plugin = AgentBarnTelegramPlatformPlugin(BotConfig(agentbarn_telegram_bot_username="@AgentBarnTestBot"))

    validated = plugin.validate_configuration({}, {}, organization_id=uuid4(), agent_id=uuid4())

    assert validated.external_identity == "@AgentBarnTestBot"


def test_the_catalogue_lists_only_offered_platforms_but_still_resolves_the_rest() -> None:
    unconfigured = AgentBarnTelegramPlatformPlugin(
        BotConfig(agentbarn_telegram_bot_token="", agentbarn_telegram_bot_username="")
    )
    registry = PlatformPluginRegistry([unconfigured, WebPlatformPlugin()])

    assert [descriptor.key for descriptor in registry.descriptors()] == ["web"]
    assert registry.require("agentbarn_telegram") is unconfigured


def test_each_connection_gets_its_own_runtime_webhook_secret() -> None:
    first = runtime_webhook_secret("driver-key-one")
    second = runtime_webhook_secret("driver-key-two")

    assert first == runtime_webhook_secret("driver-key-one")
    assert first != second
    assert "driver-key-one" not in first
    # Telegram's secret_token allows 1-256 of these characters.
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,256}", first)


def test_agentbarn_telegram_tells_the_dashboard_it_links_accounts() -> None:
    plugin = AgentBarnTelegramPlatformPlugin(BotConfig())

    assert PlatformCapability.ACCOUNT_LINKING in plugin.capabilities
    assert "account_linking" in plugin.descriptor.capabilities
