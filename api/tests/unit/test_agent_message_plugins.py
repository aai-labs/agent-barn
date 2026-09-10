from types import SimpleNamespace
from unittest.mock import patch

import pytest
from hamcrest import assert_that, equal_to

from api.domains.communications.models import OutboundTargetRequest, PlatformCapability
from api.domains.communications.plugins.discord import DiscordPlatformPlugin
from api.domains.communications.plugins.slack import SlackCredentials, SlackPlatformPlugin, SlackSettings
from api.domains.communications.plugins.teams import TeamsPlatformPlugin
from api.domains.communications.plugins.telegram import TelegramPlatformPlugin

CONFIG = SimpleNamespace(
    skip_slack_token_validation=True, skip_discord_token_validation=True, skip_telegram_token_validation=True
)


def test_slack_resolves_channel_thread_and_rejects_ambiguous_names():
    plugin = SlackPlatformPlugin(CONFIG)
    settings = SlackSettings(channel_ids=["C123"])
    credentials = SlackCredentials(bot_token="bot", app_token="app")
    with patch("api.domains.communications.plugins.slack.SlackClient") as client:
        client.return_value.get_conversation.return_value = {"id": "C123", "name": "updates", "is_im": False}
        target = plugin.resolve_outbound_target(
            settings, credentials, OutboundTargetRequest(recipient="C123", thread_id="123.456789")
        )
        assert_that(target.location.thread_id, equal_to("123.456789"))
        client.return_value.list_channels.return_value = [
            {"id": "C123", "name": "updates"},
            {"id": "C456", "name": "updates"},
        ]
        with pytest.raises(ValueError):
            plugin.resolve_outbound_target(settings, credentials, OutboundTargetRequest(recipient="#updates"))
        with pytest.raises(PermissionError):
            plugin.validate_outbound_target(SlackSettings(channel_ids=[]), target)


def test_slack_user_dm_is_resolved_and_rechecks_current_user_policy():
    plugin = SlackPlatformPlugin(CONFIG)
    settings = SlackSettings(dm_policy="allowlist", dm_user_ids=["U123"])
    with patch("api.domains.communications.plugins.slack.SlackClient") as client:
        client.return_value.open_dm.return_value = "D123"
        client.return_value.get_conversation.return_value = {"id": "D123", "is_im": True, "user": "U123"}
        target = plugin.resolve_outbound_target(
            settings,
            SlackCredentials(bot_token="b", app_token="a"),
            OutboundTargetRequest(kind="user", recipient="U123"),
        )
        assert_that(target.location.id, equal_to("D123"))
        with pytest.raises(PermissionError):
            plugin.validate_outbound_target(SlackSettings(dm_policy="off"), target)


def test_disabled_dm_is_rejected_before_opening_conversation():
    plugin = SlackPlatformPlugin(CONFIG)
    with pytest.raises(PermissionError):
        plugin.resolve_outbound_target(
            SlackSettings(),
            SlackCredentials(bot_token="b", app_token="a"),
            OutboundTargetRequest(kind="user", recipient="U123"),
        )


@pytest.mark.parametrize("plugin", [DiscordPlatformPlugin, TelegramPlatformPlugin, TeamsPlatformPlugin])
def test_only_slack_advertises_initiated_delivery(plugin):
    assert_that(PlatformCapability.AGENT_INITIATED_DELIVERY in plugin.capabilities, equal_to(False))
