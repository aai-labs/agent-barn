import io
import json
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from hamcrest import assert_that, empty, equal_to, has_length

from api.domains.communications.models import (
    CommunicationPolicyDisposition,
    CommunicationSender,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
    OutboundCommunicationEnvelope,
    PlatformCapability,
    ProcessingFeedbackStage,
)
from api.domains.communications.plugins.base import (
    InboundAdmissionContext,
    ProcessingFeedbackContext,
    provider_idempotency_key,
)
from api.domains.communications.plugins.discord import DiscordPlatformPlugin
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.plugins.slack import SlackPlatformPlugin
from api.domains.communications.plugins.teams import TeamsPlatformPlugin
from api.domains.communications.plugins.telegram import TelegramPlatformPlugin
from api.infrastructure.msteams.client import TeamsAuthError

_TEAMS_BOT_ID = "28:c9e8c047-2a74-40a2-b28a-b162d5f5327c"
_TEAMS_SERVICE_URL = "https://smba.trafficmanager.net/amer/"
_TEAMS_USER_ID = "29:1XJKJMvc5GBtc2JwZq0oj8tHZmzrQgFmB39ATiQWA85g"
_TEAMS_AAD_ID = "7faf8ab2-3d56-4244-b585-20c8a42ed2b8"
_TEAMS_CHANNEL_ID = "19:aebd0ad4d6ab42c8b9ed19c251c2fc37@thread.skype"
_TEAMS_TEAM_ID = "19:0f1e2d3c4b5a6978@thread.tacv2"


@dataclass
class ValidationConfig:
    skip_discord_token_validation: bool = True
    skip_slack_token_validation: bool = True
    skip_telegram_token_validation: bool = True
    skip_teams_token_validation: bool = True
    teams_publisher_name: str = "Agent Barn"
    teams_publisher_website_url: str = "https://example.test"
    teams_privacy_url: str = "https://example.test/privacy"
    teams_terms_url: str = "https://example.test/terms"


def test_registry_lists_shipped_plugins_in_stable_order() -> None:
    config = ValidationConfig()
    registry = PlatformPluginRegistry(
        [
            TelegramPlatformPlugin(config),
            DiscordPlatformPlugin(config),
            SlackPlatformPlugin(config),
            TeamsPlatformPlugin(config),
        ]
    )
    assert [descriptor.key for descriptor in registry.descriptors()] == ["discord", "slack", "teams", "telegram"]
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


def test_slack_admission_returns_typed_policy_dispositions() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    settings = plugin.settings_model.model_validate({"group_policy": "open"})
    context = _slack_admission_context(owned=False)

    denied_dm = plugin.admit_inbound(
        settings,
        _slack_event("hello", channel_type="im"),
        context=context,
    )
    bot_message = plugin.admit_inbound(
        settings,
        _slack_event("hello <@bot-1>", user="bot-1"),
        context=context,
    )
    mention_required = plugin.admit_inbound(
        settings,
        _slack_event("hello everyone"),
        context=context,
    )
    malformed = plugin.admit_inbound(settings, {}, context=context)
    accepted = plugin.admit_inbound(
        settings,
        _slack_event("hello <@bot-1>"),
        context=context,
    )

    assert_that(denied_dm.disposition, equal_to(CommunicationPolicyDisposition.USER_DENIED))
    assert_that(bot_message.disposition, equal_to(CommunicationPolicyDisposition.BOT_IGNORED))
    assert_that(mention_required.disposition, equal_to(CommunicationPolicyDisposition.MENTION_REQUIRED))
    assert_that(malformed.disposition, equal_to(CommunicationPolicyDisposition.MALFORMED_PAYLOAD))
    assert_that(accepted.disposition, equal_to(CommunicationPolicyDisposition.ACCEPTED))
    assert_that(accepted, has_length(1))


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


def test_slack_send_passes_a_stable_provider_idempotency_key() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "bot-value", "app_token": "app-value"})
    envelope = OutboundCommunicationEnvelope(
        source_delivery_id=uuid4(),
        location=ConversationLocation(id="channel-1", type="CHANNEL"),
        text="reply",
    )

    with patch("api.domains.communications.plugins.slack.SlackClient") as client_type:
        client_type.return_value.send_message.return_value = "sent-1"
        result = plugin.send(
            plugin.settings_model.model_validate({}),
            credentials,
            envelope,
            idempotency_key="reply-1",
        )

    assert_that(result, equal_to("sent-1"))
    client_type.return_value.send_message.assert_called_once_with(
        "channel-1",
        "reply",
        thread_id=None,
        idempotency_key=provider_idempotency_key("reply-1"),
    )


def test_discord_send_passes_a_stable_provider_idempotency_key() -> None:
    plugin = DiscordPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "bot-value"})
    envelope = OutboundCommunicationEnvelope(
        source_delivery_id=uuid4(),
        location=ConversationLocation(id="channel-1", type="CHANNEL"),
        text="reply",
    )

    with patch("api.domains.communications.plugins.discord.DiscordClient") as client_type:
        client_type.return_value.send_message.return_value = "sent-1"
        result = plugin.send(
            plugin.settings_model.model_validate({}),
            credentials,
            envelope,
            idempotency_key="reply-1",
        )

    assert_that(result, equal_to("sent-1"))
    client_type.return_value.send_message.assert_called_once_with(
        "channel-1",
        "reply",
        reply_to_id=None,
        idempotency_key=provider_idempotency_key("reply-1"),
    )


def test_telegram_send_passes_a_stable_provider_idempotency_key() -> None:
    plugin = TelegramPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "bot-value"})
    envelope = OutboundCommunicationEnvelope(
        source_delivery_id=uuid4(),
        location=ConversationLocation(id="chat-1", type="DM"),
        text="reply",
    )

    with patch("api.domains.communications.plugins.telegram.send_message", return_value="sent-1") as send:
        result = plugin.send(
            plugin.settings_model.model_validate({}),
            credentials,
            envelope,
            idempotency_key="reply-1",
        )

    assert_that(result, equal_to("sent-1"))
    send.assert_called_once_with(
        "bot-value",
        "chat-1",
        "reply",
        thread_id=None,
        idempotency_key=provider_idempotency_key("reply-1"),
    )


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


# --- Microsoft Teams ---------------------------------------------------------


def _teams_activity(**overrides: Any) -> dict[str, Any]:
    activity: dict[str, Any] = {
        "type": "message",
        "id": "1485983408511",
        "timestamp": "2026-08-25T09:18:44.211Z",
        "serviceUrl": _TEAMS_SERVICE_URL,
        "channelId": "msteams",
        "from": {"id": _TEAMS_USER_ID, "name": "Megan Bowen", "aadObjectId": _TEAMS_AAD_ID},
        "conversation": {"conversationType": "personal", "id": "a:17I0kl9EkpE1O9PH5TWrzrLNwnWWcfrU"},
        "recipient": {"id": _TEAMS_BOT_ID, "name": "Aria"},
        "text": "Hello",
        "channelData": {"tenant": {"id": "72f988bf-86f1-41af-91ab-2d7cd011db47"}},
    }
    activity.update(overrides)
    return activity


def _teams_channel_activity(**overrides: Any) -> dict[str, Any]:
    return _teams_activity(
        conversation={
            "conversationType": "channel",
            "id": f"{_TEAMS_CHANNEL_ID};messageid=1481567603816",
        },
        channelData={
            "tenant": {"id": "72f988bf-86f1-41af-91ab-2d7cd011db47"},
            "team": {"id": _TEAMS_CHANNEL_ID},
            "channel": {"id": _TEAMS_CHANNEL_ID},
        },
        entities=[{"type": "mention", "mentioned": {"id": _TEAMS_BOT_ID, "name": "Aria"}, "text": "<at>Aria</at>"}],
        **overrides,
    )


def _teams_plugin() -> TeamsPlatformPlugin:
    return TeamsPlatformPlugin(ValidationConfig())


def test_teams_descriptor_declares_webhook_ingress() -> None:
    descriptor = _teams_plugin().descriptor

    assert descriptor.key == "teams"
    assert PlatformCapability.WEBHOOK_INGRESS in descriptor.capabilities


def test_teams_normalizes_a_personal_message_as_a_dm() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"dm_policy": "open"})

    envelopes = plugin.normalize_inbound(settings, _teams_activity())

    assert_that(envelopes.disposition, equal_to(CommunicationPolicyDisposition.ACCEPTED))
    assert len(envelopes) == 1
    envelope = envelopes[0]
    assert envelope.location.type == "DM"
    assert envelope.location.id == "a:17I0kl9EkpE1O9PH5TWrzrLNwnWWcfrU"
    assert envelope.provider_message_id == "1485983408511"
    assert envelope.sender.id == "7faf8ab2-3d56-4244-b585-20c8a42ed2b8"
    assert envelope.sender.display_name == "Megan Bowen"
    assert envelope.text == "Hello"


def test_teams_carries_service_url_so_replies_can_be_addressed() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"dm_policy": "open"})

    envelope = plugin.normalize_inbound(settings, _teams_activity())[0]

    assert envelope.provider_metadata["service_url"] == _TEAMS_SERVICE_URL
    assert envelope.provider_metadata["conversation_id"] == "a:17I0kl9EkpE1O9PH5TWrzrLNwnWWcfrU"


def test_teams_channel_message_strips_the_messageid_suffix_into_the_thread() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"group_policy": "open"})

    envelope = plugin.normalize_inbound(settings, _teams_channel_activity())[0]

    # Keeping ";messageid=" on the location id would fragment one channel into
    # a separate conversation per thread.
    assert envelope.location.type == "CHANNEL"
    assert envelope.location.id == "19:aebd0ad4d6ab42c8b9ed19c251c2fc37@thread.skype"
    assert envelope.location.thread_id == "1481567603816"


def test_teams_collects_bot_mentions() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"group_policy": "open"})

    envelope = plugin.normalize_inbound(settings, _teams_channel_activity())[0]

    assert _TEAMS_BOT_ID in envelope.mentions


def test_teams_falls_back_to_the_teams_user_id_when_aad_object_id_is_absent() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"dm_policy": "open"})
    payload = _teams_activity()
    payload["from"] = {"id": "29:onlyteamsid", "name": "Megan Bowen"}

    envelope = plugin.normalize_inbound(settings, payload)[0]

    assert envelope.sender.id == "29:onlyteamsid"


def test_teams_ignores_non_message_activities() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"dm_policy": "open"})

    result = plugin.normalize_inbound(settings, _teams_activity(type="conversationUpdate"))

    assert_that(result.disposition, equal_to(CommunicationPolicyDisposition.MALFORMED_PAYLOAD))
    assert_that(result, empty())


def test_teams_ignores_the_agents_own_echo() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"dm_policy": "open"})
    payload = _teams_activity()
    payload["from"] = {"id": _TEAMS_BOT_ID, "name": "Aria"}

    result = plugin.normalize_inbound(settings, payload)

    assert_that(result.disposition, equal_to(CommunicationPolicyDisposition.BOT_IGNORED))
    assert_that(result, empty())


def test_teams_rejects_a_message_without_a_sender_id() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"dm_policy": "open"})
    payload = _teams_activity()
    payload["from"] = {"name": "Megan Bowen"}

    result = plugin.normalize_inbound(settings, payload)

    assert_that(result.disposition, equal_to(CommunicationPolicyDisposition.MALFORMED_PAYLOAD))
    assert_that(result, empty())


def test_teams_dm_policy_off_drops_direct_messages() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"dm_policy": "off"})

    result = plugin.normalize_inbound(settings, _teams_activity())

    assert_that(result.disposition, equal_to(CommunicationPolicyDisposition.USER_DENIED))
    assert_that(result, empty())


def test_teams_dm_allowlist_admits_only_listed_senders() -> None:
    plugin = _teams_plugin()
    allowed = plugin.settings_model.model_validate(
        {"dm_policy": "allowlist", "dm_user_ids": ["7faf8ab2-3d56-4244-b585-20c8a42ed2b8"]}
    )
    blocked = plugin.settings_model.model_validate({"dm_policy": "allowlist", "dm_user_ids": ["someone-else"]})

    assert len(plugin.normalize_inbound(allowed, _teams_activity())) == 1
    result = plugin.normalize_inbound(blocked, _teams_activity())

    assert_that(result.disposition, equal_to(CommunicationPolicyDisposition.USER_DENIED))
    assert_that(result, empty())


def test_teams_group_allowlist_matches_the_stripped_channel_id() -> None:
    plugin = _teams_plugin()
    allowed = plugin.settings_model.model_validate(
        {"group_policy": "allowlist", "channel_ids": ["19:aebd0ad4d6ab42c8b9ed19c251c2fc37@thread.skype"]}
    )
    blocked = plugin.settings_model.model_validate(
        {"group_policy": "allowlist", "channel_ids": ["19:other@thread.skype"]}
    )

    assert len(plugin.normalize_inbound(allowed, _teams_channel_activity())) == 1
    result = plugin.normalize_inbound(blocked, _teams_channel_activity())

    assert_that(result.disposition, equal_to(CommunicationPolicyDisposition.CHANNEL_DENIED))
    assert_that(result, empty())


def test_teams_captures_addressable_ids_for_replies() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"dm_policy": "open"})

    envelope = plugin.normalize_inbound(settings, _teams_activity())[0]

    # sender.id is the Entra object id, used for policy matching. Replies must
    # be addressed with the Teams ids instead.
    assert envelope.sender.id == _TEAMS_AAD_ID
    assert envelope.provider_metadata["from_id"] == _TEAMS_USER_ID
    assert envelope.provider_metadata["recipient_id"] == _TEAMS_BOT_ID


def test_teams_dm_is_labelled_with_the_sender_name() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"dm_policy": "open"})

    envelope = plugin.normalize_inbound(settings, _teams_activity())[0]

    assert envelope.location.display_name == "Megan Bowen"


def test_teams_conversation_name_wins_over_the_sender_name() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"dm_policy": "open", "group_policy": "open"})
    payload = _teams_activity()
    payload["conversation"] = {**payload["conversation"], "name": "Release planning"}

    envelope = plugin.normalize_inbound(settings, payload)[0]

    assert envelope.location.display_name == "Release planning"


def test_teams_channel_without_a_name_stays_unlabelled() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"group_policy": "open"})

    envelope = plugin.normalize_inbound(settings, _teams_channel_activity())[0]

    # Teams omits channelData.channel.name on ordinary messages, so there is
    # nothing to label a team channel with without Microsoft Graph.
    assert envelope.location.display_name is None


def test_teams_send_posts_a_complete_activity_to_the_conversation() -> None:
    plugin = _teams_plugin()
    credentials = plugin.credentials_model.model_validate(
        {"app_id": "app-1", "app_password": "secret", "tenant_id": "tenant-1"}
    )
    envelope = OutboundCommunicationEnvelope(
        source_delivery_id=uuid4(),
        location=ConversationLocation(id=_TEAMS_CHANNEL_ID, type="CHANNEL"),
        text="Acknowledged",
        reply_to_provider_message_id="1485983408511",
        provider_metadata={
            "service_url": _TEAMS_SERVICE_URL,
            "conversation_id": f"{_TEAMS_CHANNEL_ID};messageid=1481567603816",
            "from_id": _TEAMS_USER_ID,
            "recipient_id": _TEAMS_BOT_ID,
        },
    )

    with (
        patch("api.domains.communications.plugins.teams.acquire_token", return_value="tok"),
        patch("api.domains.communications.plugins.teams.send_activity", return_value="sent-1") as send,
    ):
        result = plugin.send(
            plugin.settings_model.model_validate({}),
            credentials,
            envelope,
            idempotency_key="reply-1",
        )

        assert_that(result, equal_to("sent-1"))

    service_url, conversation_id, activity, token = send.call_args.args
    assert service_url == _TEAMS_SERVICE_URL
    # The thread lives in the conversation id, so it must be sent whole.
    assert conversation_id == f"{_TEAMS_CHANNEL_ID};messageid=1481567603816"
    assert token == "tok"
    assert activity["type"] == "message"
    assert activity["text"] == "Acknowledged"
    assert activity["conversation"] == {"id": f"{_TEAMS_CHANNEL_ID};messageid=1481567603816"}
    assert activity["from"] == {"id": _TEAMS_BOT_ID}
    assert activity["recipient"] == {"id": _TEAMS_USER_ID}
    assert activity["replyToId"] == "1485983408511"
    assert_that(send.call_args.kwargs["idempotency_key"], equal_to(provider_idempotency_key("reply-1")))


def test_teams_send_without_a_service_url_is_rejected() -> None:
    plugin = _teams_plugin()
    credentials = plugin.credentials_model.model_validate(
        {"app_id": "app-1", "app_password": "secret", "tenant_id": "tenant-1"}
    )
    envelope = OutboundCommunicationEnvelope(
        source_delivery_id=uuid4(),
        location=ConversationLocation(id=_TEAMS_CHANNEL_ID, type="CHANNEL"),
        text="Acknowledged",
    )

    with pytest.raises(ValueError, match="serviceUrl"):
        plugin.send(plugin.settings_model.model_validate({}), credentials, envelope, idempotency_key="reply-1")


def test_teams_strips_the_agents_own_mention_from_the_text() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"group_policy": "open"})
    payload = _teams_channel_activity(text="<at>Aria</at> reply")

    envelope = plugin.normalize_inbound(settings, payload)[0]

    # Leaving the markup in makes the agent read its own name as a third party.
    assert envelope.text == "reply"


def test_teams_keeps_mentions_of_other_people() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"group_policy": "open"})
    payload = _teams_channel_activity(text="<at>Aria</at> ask <at>Pranav</at> about it")
    payload["entities"] = [
        {"type": "mention", "mentioned": {"id": _TEAMS_BOT_ID, "name": "Aria"}, "text": "<at>Aria</at>"},
        {"type": "mention", "mentioned": {"id": _TEAMS_USER_ID, "name": "Pranav"}, "text": "<at>Pranav</at>"},
    ]

    envelope = plugin.normalize_inbound(settings, payload)[0]

    assert envelope.text == "ask <at>Pranav</at> about it"


def test_teams_leaves_text_untouched_without_mention_entities() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"dm_policy": "open"})
    payload = _teams_activity(text="Aria can you help")

    envelope = plugin.normalize_inbound(settings, payload)[0]

    assert envelope.text == "Aria can you help"


def _teams_channel_envelope(**overrides: Any) -> NormalizedCommunicationEnvelope:
    fields: dict[str, Any] = {
        "provider_message_id": "1485983408511",
        "occurred_at": datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        "location": ConversationLocation(id=_TEAMS_CHANNEL_ID, type="CHANNEL"),
        "text": "hello",
        "provider_metadata": {
            "service_url": _TEAMS_SERVICE_URL,
            "team_id": _TEAMS_TEAM_ID,
        },
    }
    fields.update(overrides)
    return NormalizedCommunicationEnvelope(**fields)


def _teams_credentials(plugin: TeamsPlatformPlugin):
    return plugin.credentials_model.model_validate(
        {"app_id": "app-1", "app_password": "secret", "tenant_id": "tenant-1"}
    )


def test_teams_channel_message_carries_the_team_id_for_enrichment() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({"group_policy": "open"})

    envelope = plugin.normalize_inbound(settings, _teams_channel_activity())[0]

    assert envelope.provider_metadata["team_id"] == _TEAMS_CHANNEL_ID


def test_teams_enrich_resolves_a_channel_name() -> None:
    plugin = _teams_plugin()
    envelope = _teams_channel_envelope()

    with (
        patch("api.domains.communications.plugins.teams.acquire_token", return_value="tok"),
        patch(
            "api.domains.communications.plugins.teams.list_team_channels",
            return_value={_TEAMS_CHANNEL_ID: "Release planning"},
        ),
    ):
        enriched = plugin.enrich_inbound(
            plugin.settings_model.model_validate({}), _teams_credentials(plugin), [envelope]
        )

    assert enriched[0].location.display_name == "Release planning"


def test_teams_enrich_labels_the_general_channel() -> None:
    plugin = _teams_plugin()
    # Teams returns a null name for General, and its channel id equals the team id.
    envelope = _teams_channel_envelope(
        location=ConversationLocation(id=_TEAMS_TEAM_ID, type="CHANNEL"),
    )

    with (
        patch("api.domains.communications.plugins.teams.acquire_token", return_value="tok"),
        patch("api.domains.communications.plugins.teams.list_team_channels", return_value={_TEAMS_TEAM_ID: None}),
    ):
        enriched = plugin.enrich_inbound(
            plugin.settings_model.model_validate({}), _teams_credentials(plugin), [envelope]
        )

    assert enriched[0].location.display_name == "General"


def test_teams_enrich_keeps_a_name_the_payload_already_supplied() -> None:
    plugin = _teams_plugin()
    envelope = _teams_channel_envelope(
        location=ConversationLocation(id=_TEAMS_CHANNEL_ID, type="CHANNEL", display_name="From payload"),
    )

    with patch("api.domains.communications.plugins.teams.list_team_channels") as lookup:
        enriched = plugin.enrich_inbound(
            plugin.settings_model.model_validate({}), _teams_credentials(plugin), [envelope]
        )

    lookup.assert_not_called()
    assert enriched[0].location.display_name == "From payload"


def test_teams_enrich_skips_direct_messages() -> None:
    plugin = _teams_plugin()
    envelope = _teams_channel_envelope(location=ConversationLocation(id="a:dm", type="DM"))

    with patch("api.domains.communications.plugins.teams.list_team_channels") as lookup:
        plugin.enrich_inbound(plugin.settings_model.model_validate({}), _teams_credentials(plugin), [envelope])

    lookup.assert_not_called()


def test_teams_enrich_lookup_failure_leaves_the_envelope_intact() -> None:
    plugin = _teams_plugin()
    envelope = _teams_channel_envelope()

    with (
        patch("api.domains.communications.plugins.teams.acquire_token", return_value="tok"),
        patch(
            "api.domains.communications.plugins.teams.list_team_channels",
            side_effect=RuntimeError("Teams unreachable"),
        ),
    ):
        enriched = plugin.enrich_inbound(
            plugin.settings_model.model_validate({}), _teams_credentials(plugin), [envelope]
        )

    assert enriched[0].location.id == _TEAMS_CHANNEL_ID
    assert enriched[0].location.display_name is None


def test_slack_does_not_advertise_an_app_package_it_cannot_build() -> None:
    plugin = SlackPlatformPlugin(ValidationConfig())

    assert PlatformCapability.APPLICATION_PROVISIONING not in plugin.descriptor.capabilities
    with pytest.raises(NotImplementedError):
        plugin.build_app_package(
            plugin.settings_model.model_validate({}),
            plugin.credentials_model.model_validate({"bot_token": "xoxb-1", "app_token": "xapp-1"}),
            connection_id=uuid4(),
            display_name="Aria",
        )


def test_teams_descriptor_declares_application_provisioning() -> None:
    assert PlatformCapability.APPLICATION_PROVISIONING in _teams_plugin().descriptor.capabilities


def test_teams_app_package_contains_a_valid_manifest_and_icons() -> None:
    plugin = _teams_plugin()
    connection_id = uuid4()

    filename, payload = plugin.build_app_package(
        plugin.settings_model.model_validate({}),
        _teams_credentials(plugin),
        connection_id=connection_id,
        display_name="Aria",
    )

    assert filename == "aria-teams-app.zip"
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        assert sorted(archive.namelist()) == ["color.png", "manifest.json", "outline.png"]
        manifest = json.loads(archive.read("manifest.json"))
        assert archive.read("color.png").startswith(b"\x89PNG")
        assert archive.read("outline.png").startswith(b"\x89PNG")

    assert manifest["manifestVersion"] == "1.17"
    assert manifest["bots"][0]["botId"] == "app-1"
    assert manifest["bots"][0]["scopes"] == ["personal", "team", "groupChat"]
    assert manifest["developer"]["websiteUrl"] == "https://example.test"


def test_teams_app_package_manifest_id_is_stable_per_connection() -> None:
    plugin = _teams_plugin()
    settings = plugin.settings_model.model_validate({})
    credentials = _teams_credentials(plugin)
    connection_id = uuid4()

    def manifest_id(cid) -> str:
        _, payload = plugin.build_app_package(settings, credentials, connection_id=cid, display_name="Aria")
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            return json.loads(archive.read("manifest.json"))["id"]

    # Re-downloading must update the tenant's existing app, not register a second.
    assert manifest_id(connection_id) == manifest_id(connection_id)
    assert manifest_id(connection_id) != manifest_id(uuid4())


def test_teams_app_package_never_carries_credentials() -> None:
    plugin = _teams_plugin()

    _, payload = plugin.build_app_package(
        plugin.settings_model.model_validate({}),
        _teams_credentials(plugin),
        connection_id=uuid4(),
        display_name="Aria",
    )

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifest = archive.read("manifest.json").decode()
    assert "secret" not in manifest
    assert "tenant-1" not in manifest


def test_teams_app_package_rejects_a_non_https_publisher_url() -> None:
    config = ValidationConfig()
    config.teams_privacy_url = "http://internal.cluster.local/privacy"
    plugin = TeamsPlatformPlugin(config)

    with pytest.raises(ValueError, match="privacy policy"):
        plugin.build_app_package(
            plugin.settings_model.model_validate({}),
            _teams_credentials(plugin),
            connection_id=uuid4(),
            display_name="Aria",
        )


def test_teams_manifest_uses_only_fields_its_declared_schema_allows() -> None:
    plugin = _teams_plugin()

    _, payload = plugin.build_app_package(
        plugin.settings_model.model_validate({}),
        _teams_credentials(plugin),
        connection_id=uuid4(),
        display_name="Aria",
    )
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        manifest = json.loads(archive.read("manifest.json"))

    # The Teams schema sets additionalProperties:false, so a field carried over
    # from an older schema version fails upload with an unparseable-manifest
    # error. packageName was valid through v1.16 and removed in v1.17.
    assert manifest["manifestVersion"] == "1.17"
    assert f"/v{manifest['manifestVersion']}/" in manifest["$schema"]
    assert "packageName" not in manifest
    assert set(manifest) <= {
        "$schema",
        "manifestVersion",
        "version",
        "id",
        "developer",
        "name",
        "description",
        "icons",
        "accentColor",
        "bots",
        "permissions",
        "validDomains",
    }
    assert set(manifest["bots"][0]["scopes"]) <= {"team", "personal", "groupChat"}


def test_teams_rejected_webhook_token_raises_the_gateways_permission_error() -> None:
    plugin = _teams_plugin()

    with patch(
        "api.domains.communications.plugins.teams.verify_inbound_jwt",
        side_effect=TeamsAuthError("Bot Framework token verification failed"),
    ):
        with pytest.raises(PermissionError):
            plugin.verify_webhook(_teams_credentials(plugin), {"type": "message"}, "Bearer nope")


def test_teams_rejected_credentials_raise_value_error_like_every_other_plugin() -> None:
    plugin = TeamsPlatformPlugin(replace(ValidationConfig(), skip_teams_token_validation=False))

    with patch(
        "api.domains.communications.plugins.teams.acquire_token",
        side_effect=TeamsAuthError("Microsoft rejected the Teams credentials."),
    ):
        with pytest.raises(ValueError):
            plugin.validate_external(plugin.settings_model.model_validate({}), _teams_credentials(plugin))
