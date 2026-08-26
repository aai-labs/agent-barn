from dataclasses import dataclass, replace
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from api.domains.communications.models import (
    CommunicationSender,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
    PlatformCapability,
    ProcessingFeedbackStage,
)
from api.domains.communications.plugins.base import InboundAdmissionContext, ProcessingFeedbackContext
from api.domains.communications.plugins.discord import DiscordPlatformPlugin
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.plugins.slack import SlackPlatformPlugin
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
        ]
    )
    assert [descriptor.key for descriptor in registry.descriptors()] == ["discord", "slack", "telegram"]
    assert PlatformCapability.DIRECTORY_DISCOVERY in registry.require("slack").descriptor.capabilities


def test_registry_rejects_duplicate_platform_keys() -> None:
    config = ValidationConfig()
    with pytest.raises(ValueError, match="Duplicate Platform Plugin key: telegram"):
        PlatformPluginRegistry([TelegramPlatformPlugin(config), TelegramPlatformPlugin(config)])


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


def _slack_event(
    text: str,
    *,
    thread_ts: str | None = None,
    channel_type: str = "channel",
    subtype: str | None = None,
    user: str = "user-1",
) -> dict:
    event = {
        "type": "message",
        "channel": "channel-1" if channel_type != "im" else "dm-1",
        "channel_type": channel_type,
        "user": user,
        "ts": "1724320800.000100",
        "text": text,
    }
    if thread_ts is not None:
        event["thread_ts"] = thread_ts
    if subtype is not None:
        event["subtype"] = subtype
    return {"event": event, "agentbarn_bot_user_id": "bot-1"}


def _slack_admission_context(*, owned: bool) -> InboundAdmissionContext:
    return InboundAdmissionContext(
        connection_id=uuid4(),
        thread_is_agent_owned=lambda _location: owned,
    )


def test_slack_plugin_requires_a_direct_bot_mention_for_channel_messages() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    settings = plugin.settings_model.model_validate({"group_policy": "open"})

    mentioned = plugin.admit_inbound(
        settings,
        _slack_event("hello <@bot-1|agent>", thread_ts=None),
        context=_slack_admission_context(owned=False),
    )
    unmentioned = plugin.admit_inbound(
        settings,
        _slack_event("hello everyone", thread_ts=None),
        context=_slack_admission_context(owned=True),
    )

    assert len(mentioned) == 1
    assert mentioned[0].mentions == ["bot-1"]
    assert unmentioned == []


def test_slack_message_identity_uses_timestamp_for_reaction_feedback() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    settings = plugin.settings_model.model_validate({"group_policy": "open"})
    payload = _slack_event("hello <@bot-1|agent>")
    payload["event"]["client_msg_id"] = "client-generated-id"

    envelopes = plugin.admit_inbound(
        settings,
        payload,
        context=_slack_admission_context(owned=False),
    )

    assert len(envelopes) == 1
    assert envelopes[0].provider_message_id == "1724320800.000100"
    assert envelopes[0].provider_metadata["client_msg_id"] == "client-generated-id"


def test_slack_every_message_policy_requires_mentions_inside_threads() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    settings = plugin.settings_model.model_validate({"group_policy": "open", "thread_mention_policy": "every_message"})

    assert (
        plugin.admit_inbound(
            settings,
            _slack_event("follow-up", thread_ts="1724320800.000100"),
            context=_slack_admission_context(owned=True),
        )
        == []
    )


def test_slack_start_only_policy_accepts_unmentioned_replies_only_in_owned_threads() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    settings = plugin.settings_model.model_validate({"group_policy": "open", "thread_mention_policy": "start_only"})

    owned_reply = plugin.admit_inbound(
        settings,
        _slack_event("follow-up", thread_ts="1724320800.000100"),
        context=_slack_admission_context(owned=True),
    )
    arbitrary_reply = plugin.admit_inbound(
        settings,
        _slack_event("follow-up", thread_ts="other-root"),
        context=_slack_admission_context(owned=False),
    )

    assert len(owned_reply) == 1
    assert arbitrary_reply == []


def test_slack_dm_and_bot_message_policies_remain_before_mention_admission() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    open_dms = plugin.settings_model.model_validate({"group_policy": "open", "dm_policy": "open"})

    dm = plugin.admit_inbound(
        open_dms,
        _slack_event("hello without a mention", channel_type="im"),
        context=_slack_admission_context(owned=False),
    )
    bot_message = plugin.admit_inbound(
        open_dms,
        _slack_event("<@bot-1> bot echo", user="bot-1"),
        context=_slack_admission_context(owned=False),
    )
    subtype_message = plugin.admit_inbound(
        open_dms,
        _slack_event("edited", subtype="message_changed", channel_type="im"),
        context=_slack_admission_context(owned=False),
    )

    assert len(dm) == 1
    assert bot_message == []
    assert subtype_message == []


def test_slack_ignores_app_mention_events_to_avoid_duplicate_message_delivery() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    settings = plugin.settings_model.model_validate({"group_policy": "open"})
    payload = _slack_event("<@bot-1> hello")
    payload["event"]["type"] = "app_mention"

    assert plugin.admit_inbound(settings, payload, context=_slack_admission_context(owned=False)) == []


def test_slack_processing_feedback_uses_reactions_and_thread_status() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    settings = plugin.settings_model.model_validate({})
    credentials = plugin.credentials_model.model_validate({"bot_token": "xoxb-token", "app_token": "xapp-token"})
    context = ProcessingFeedbackContext(
        connection_id=uuid4(),
        stage=ProcessingFeedbackStage.ACCEPTED,
        location=ConversationLocation(id="channel-1", type="CHANNEL", thread_id="root-1"),
        provider_message_id="root-1",
    )

    with patch("api.domains.communications.plugins.slack.SlackClient") as client_type:
        client = client_type.return_value
        plugin.processing_feedback(settings, credentials, context)
        plugin.processing_feedback(
            settings,
            credentials,
            replace(context, stage=ProcessingFeedbackStage.CLAIMED),
        )
        plugin.processing_feedback(
            settings,
            credentials,
            replace(context, stage=ProcessingFeedbackStage.SUCCEEDED),
        )

    assert client.add_reaction.call_args_list[0].args == ("channel-1", "root-1", "eyes")
    client.set_thread_status.assert_called_once_with("channel-1", "root-1", "is thinking...")
    client.clear_thread_status.assert_called_once_with("channel-1", "root-1")
    client.remove_reaction.assert_called_once_with("channel-1", "root-1", "eyes")
    assert client.add_reaction.call_count == 2
    assert client.add_reaction.call_args_list[-1].args == ("channel-1", "root-1", "white_check_mark")


# --- inbound name enrichment ------------------------------------------------


def _envelope(*, location: ConversationLocation, sender: CommunicationSender) -> NormalizedCommunicationEnvelope:
    return NormalizedCommunicationEnvelope(
        provider_message_id="1",
        occurred_at=datetime.now(UTC),
        location=location,
        sender=sender,
        text="hi",
    )


def test_slack_enrich_inbound_preserves_names_already_in_the_payload() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "xoxb-token", "app_token": "xapp-token"})
    envelope = _envelope(
        location=ConversationLocation(id="C1", type="CHANNEL", display_name="general"),
        sender=CommunicationSender(id="U1", display_name="Alice"),
    )

    with patch("api.domains.communications.plugins.slack.SlackClient") as client_type:
        enriched = plugin.enrich_inbound(plugin.settings_model.model_validate({}), credentials, [envelope])

    assert enriched == [envelope]
    client_type.return_value.get_user_display_name.assert_not_called()
    client_type.return_value.get_channel_name.assert_not_called()


def test_slack_enrich_inbound_fills_missing_sender_and_channel_name() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "xoxb-token", "app_token": "xapp-token"})
    envelope = _envelope(
        location=ConversationLocation(id="C1", type="CHANNEL"),
        sender=CommunicationSender(id="U1"),
    )

    with patch("api.domains.communications.plugins.slack.SlackClient") as client_type:
        client = client_type.return_value
        client.get_user_display_name.return_value = "Alice"
        client.get_channel_name.return_value = "general"
        enriched = plugin.enrich_inbound(plugin.settings_model.model_validate({}), credentials, [envelope])

    assert enriched[0].sender.display_name == "Alice"
    assert enriched[0].location.display_name == "general"
    client.get_user_display_name.assert_called_once_with("U1")
    client.get_channel_name.assert_called_once_with("C1")


def test_slack_enrich_inbound_resolves_dm_participant_name() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "xoxb-token", "app_token": "xapp-token"})
    envelope = _envelope(
        location=ConversationLocation(id="D1", type="DM"),
        sender=CommunicationSender(id="U1"),
    )

    with patch("api.domains.communications.plugins.slack.SlackClient") as client_type:
        client = client_type.return_value
        client.get_dm_participant_name.return_value = "Alice"
        enriched = plugin.enrich_inbound(plugin.settings_model.model_validate({}), credentials, [envelope])

    assert enriched[0].location.display_name == "Alice"
    client.get_dm_participant_name.assert_called_once_with("D1")
    client.get_channel_name.assert_not_called()


def test_slack_enrich_inbound_lookup_failure_leaves_envelope_valid_with_ids_intact() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "xoxb-token", "app_token": "xapp-token"})
    envelope = _envelope(
        location=ConversationLocation(id="C1", type="CHANNEL"),
        sender=CommunicationSender(id="U1"),
    )

    with patch("api.domains.communications.plugins.slack.SlackClient") as client_type:
        client = client_type.return_value
        client.get_user_display_name.side_effect = RuntimeError("missing users:read scope")
        client.get_channel_name.return_value = "general"
        enriched = plugin.enrich_inbound(plugin.settings_model.model_validate({}), credentials, [envelope])

    assert enriched[0].sender.id == "U1"
    assert enriched[0].sender.display_name is None
    assert enriched[0].location.display_name == "general"


def test_discord_enrich_inbound_preserves_member_nickname_already_in_payload() -> None:
    plugin = DiscordPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "discord-token"})
    envelope = _envelope(
        location=ConversationLocation(id="channel-1", type="CHANNEL"),
        sender=CommunicationSender(id="user-1", display_name="Server Nickname"),
    )

    with patch("api.domains.communications.plugins.discord.DiscordClient") as client_type:
        client = client_type.return_value
        client.get_channel_display_name.return_value = "ops-alerts"
        enriched = plugin.enrich_inbound(plugin.settings_model.model_validate({}), credentials, [envelope])

    assert enriched[0].sender.display_name == "Server Nickname"
    assert enriched[0].location.display_name == "ops-alerts"
    client.get_user_display_name.assert_not_called()


def test_discord_enrich_inbound_fills_missing_channel_name() -> None:
    plugin = DiscordPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "discord-token"})
    envelope = _envelope(
        location=ConversationLocation(id="channel-1", type="CHANNEL"),
        sender=CommunicationSender(id="user-1"),
    )

    with patch("api.domains.communications.plugins.discord.DiscordClient") as client_type:
        client = client_type.return_value
        client.get_user_display_name.return_value = "Ada"
        client.get_channel_display_name.return_value = "ops-alerts"
        enriched = plugin.enrich_inbound(plugin.settings_model.model_validate({}), credentials, [envelope])

    assert enriched[0].sender.display_name == "Ada"
    assert enriched[0].location.display_name == "ops-alerts"


def test_discord_enrich_inbound_lookup_failure_leaves_envelope_valid_with_ids_intact() -> None:
    plugin = DiscordPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "discord-token"})
    envelope = _envelope(
        location=ConversationLocation(id="channel-1", type="CHANNEL"),
        sender=CommunicationSender(id="user-1"),
    )

    with patch("api.domains.communications.plugins.discord.DiscordClient") as client_type:
        client = client_type.return_value
        client.get_user_display_name.side_effect = RuntimeError("Discord unreachable")
        client.get_channel_display_name.return_value = "ops-alerts"
        enriched = plugin.enrich_inbound(plugin.settings_model.model_validate({}), credentials, [envelope])

    assert enriched[0].sender.id == "user-1"
    assert enriched[0].sender.display_name is None
    assert enriched[0].location.display_name == "ops-alerts"


def test_telegram_enrich_inbound_preserves_names_already_in_the_payload() -> None:
    plugin = TelegramPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "123:ABC"})
    envelope = _envelope(
        location=ConversationLocation(id="-100123", type="CHANNEL", display_name="Dev Chat"),
        sender=CommunicationSender(id="42", display_name="Alice"),
    )

    with patch("api.domains.communications.plugins.telegram.get_chat_display_name") as lookup:
        enriched = plugin.enrich_inbound(plugin.settings_model.model_validate({}), credentials, [envelope])

    assert enriched == [envelope]
    lookup.assert_not_called()


def test_telegram_enrich_inbound_falls_back_when_payload_lacks_names() -> None:
    plugin = TelegramPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "123:ABC"})
    envelope = _envelope(
        location=ConversationLocation(id="42", type="DM"),
        sender=CommunicationSender(id="42"),
    )

    with patch(
        "api.domains.communications.plugins.telegram.get_chat_display_name",
        return_value="Alice",
    ) as lookup:
        enriched = plugin.enrich_inbound(plugin.settings_model.model_validate({}), credentials, [envelope])

    assert enriched[0].sender.display_name == "Alice"
    assert enriched[0].location.display_name == "Alice"
    assert lookup.call_args_list == [
        (("123:ABC", "42"),),
        (("123:ABC", "42"),),
    ]


def test_telegram_enrich_inbound_lookup_failure_leaves_envelope_valid_with_ids_intact() -> None:
    plugin = TelegramPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "123:ABC"})
    envelope = _envelope(
        location=ConversationLocation(id="-100123", type="CHANNEL"),
        sender=CommunicationSender(id="42"),
    )

    with patch(
        "api.domains.communications.plugins.telegram.get_chat_display_name",
        side_effect=RuntimeError("Telegram unreachable"),
    ):
        enriched = plugin.enrich_inbound(plugin.settings_model.model_validate({}), credentials, [envelope])

    assert enriched[0].sender.id == "42"
    assert enriched[0].sender.display_name is None
    assert enriched[0].location.display_name is None
