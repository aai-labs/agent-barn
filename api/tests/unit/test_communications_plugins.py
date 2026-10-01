import io
import json
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from hamcrest import assert_that, empty, equal_to, is_

from api.domains.communications.models import (
    CommunicationPolicyDisposition,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
    PlatformCapability,
)
from api.domains.communications.plugins.base import (
    GatewayDeliveryPlugin,
    WebhookRequest,
)
from api.domains.communications.plugins.discord import DiscordPlatformPlugin
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.plugins.slack import SlackPlatformPlugin
from api.domains.communications.plugins.teams import TeamsPlatformPlugin, TeamsSettings
from api.domains.communications.plugins.telegram import TelegramPlatformPlugin
from api.domains.communications.plugins.web import WebPlatformPlugin
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
            WebPlatformPlugin(),
        ]
    )
    assert [descriptor.key for descriptor in registry.descriptors()] == [
        "discord",
        "slack",
        "teams",
        "telegram",
        "web",
    ]
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


def test_discord_plugin_builds_the_recommended_install_link_from_the_application() -> None:
    plugin = DiscordPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "bot-value"})

    with patch("api.domains.communications.plugins.discord.DiscordClient") as client_type:
        client_type.return_value.get_current_application.return_value = {"id": "123456789012345678"}
        url = plugin.build_install_link(plugin.settings_model.model_validate({}), credentials)

    assert_that(
        url,
        equal_to(
            "https://discord.com/oauth2/authorize"
            "?client_id=123456789012345678&scope=bot%20applications.commands&permissions=274878286912"
        ),
    )


def test_platforms_without_install_links_reject_the_seam() -> None:
    plugin = TelegramPlatformPlugin(ValidationConfig())
    credentials = plugin.credentials_model.model_validate({"bot_token": "123:token"})

    with pytest.raises(NotImplementedError, match="telegram does not implement bot install links"):
        plugin.build_install_link(plugin.settings_model.model_validate({}), credentials)


# --- inbound name enrichment ------------------------------------------------


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
    assert_that(PlatformCapability.PROCESSING_FEEDBACK in descriptor.capabilities, is_(False))


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


def test_teams_runtime_relay_applies_dm_policy_to_approval_invokes() -> None:
    plugin = _teams_plugin()
    allowed = TeamsSettings.model_validate({"dm_policy": "allowlist", "dm_user_ids": [_TEAMS_AAD_ID]})
    blocked = TeamsSettings.model_validate({"dm_policy": "allowlist", "dm_user_ids": ["someone-else"]})
    invoke = _teams_activity(type="invoke")

    assert plugin.runtime_relay_disposition(allowed, invoke) == CommunicationPolicyDisposition.ACCEPTED
    assert plugin.runtime_relay_disposition(blocked, invoke) == CommunicationPolicyDisposition.USER_DENIED


def test_teams_runtime_relay_forwards_authenticated_lifecycle_activities() -> None:
    plugin = _teams_plugin()
    settings = TeamsSettings.model_validate({})

    assert (
        plugin.runtime_relay_disposition(settings, _teams_activity(type="conversationUpdate"))
        == CommunicationPolicyDisposition.ACCEPTED
    )


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


def _teams_credentials(plugin: TeamsPlatformPlugin):
    return plugin.credentials_model.model_validate(
        {"app_id": "app-1", "app_password": "secret", "tenant_id": "tenant-1"}
    )


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
    assert manifest["bots"][0]["supportsFiles"] is True
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


def _webhook_request(payload: dict, *, authorization: str = "", headers: dict | None = None) -> WebhookRequest:
    """Build the request a plugin sees, with raw bytes that really are this payload."""
    return WebhookRequest(
        raw_body=json.dumps(payload).encode(),
        payload=payload,
        authorization=authorization,
        headers=headers or {},
    )


def test_teams_rejected_webhook_token_raises_the_gateways_permission_error() -> None:
    plugin = _teams_plugin()

    with patch(
        "api.domains.communications.plugins.teams.verify_inbound_jwt",
        side_effect=TeamsAuthError("Bot Framework token verification failed"),
    ):
        with pytest.raises(PermissionError):
            plugin.verify_webhook(
                _teams_credentials(plugin),
                _webhook_request({"type": "message"}, authorization="Bearer nope"),
            )


def test_teams_rejected_credentials_raise_value_error_like_every_other_plugin() -> None:
    plugin = TeamsPlatformPlugin(replace(ValidationConfig(), skip_teams_token_validation=False))

    with patch(
        "api.domains.communications.plugins.teams.acquire_token",
        side_effect=TeamsAuthError("Microsoft rejected the Teams credentials."),
    ):
        with pytest.raises(ValueError):
            plugin.validate_external(plugin.settings_model.model_validate({}), _teams_credentials(plugin))


def test_teams_offers_guidance_for_after_the_connection_is_saved() -> None:
    descriptor = _teams_plugin().descriptor

    # Steps needing the saved Connection's webhook URL or app package cannot be
    # actioned from the creation form, so they are surfaced alongside them.
    assert "Messaging endpoint" in (descriptor.post_setup_hint or "")
    assert "app package" in (descriptor.post_setup_hint or "")
    assert "client secret" in (descriptor.setup_hint or "")


@pytest.mark.parametrize(
    "plugin_class",
    [WebPlatformPlugin],
)
def test_web_delivery_hands_the_runtime_the_message_exactly_as_stored(plugin_class) -> None:
    envelope = NormalizedCommunicationEnvelope(
        provider_message_id="1724264405.531769",
        occurred_at=datetime(2026, 8, 24, 10, 0, tzinfo=UTC),
        location=ConversationLocation(id="C123", type="CHANNEL"),
        text="the original message text",
    )

    assert plugin_class.runtime_prompt is GatewayDeliveryPlugin.runtime_prompt
    assert GatewayDeliveryPlugin.runtime_prompt(plugin_class.__new__(plugin_class), envelope) == envelope.text
