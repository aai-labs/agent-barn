import logging
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import Field

from api.domains.communications.models import (
    CommunicationSender,
    ConversationLocation,
    CredentialUniquenessScope,
    NormalizedCommunicationEnvelope,
    OutboundCommunicationEnvelope,
    PlatformCapability,
)
from api.domains.communications.plugins.base import (
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
)
from api.infrastructure.msteams.client import acquire_token, send_activity, verify_inbound_jwt

logger = logging.getLogger(__name__)

_MESSAGE_ID_SEPARATOR = ";messageid="
_PERSONAL_CONVERSATION_TYPE = "personal"


class TeamsValidationConfig(Protocol):
    skip_teams_token_validation: bool


class TeamsSettings(PlatformSettings):
    channel_ids: list[str] = Field(
        default_factory=list,
        title="Allowed channels",
        description="Channel IDs this agent may read and post in. Used when Channel access is Allowlist.",
    )
    dm_user_ids: list[str] = Field(
        default_factory=list,
        title="Allowed DM senders",
        description="User IDs allowed to direct-message this agent. Used when Direct messages is Allowlist.",
    )
    group_policy: str = Field(
        default="allowlist",
        pattern="^(open|allowlist)$",
        title="Channel access",
        description="Open responds in any channel it's added to. Allowlist restricts it to Allowed channels.",
    )
    dm_policy: str = Field(
        default="off",
        pattern="^(off|open|allowlist)$",
        title="Direct messages",
        description="Off ignores DMs, Open accepts DMs from anyone, Allowlist restricts to Allowed DM senders.",
    )


class TeamsCredentials(PlatformCredentials):
    app_id: str = Field(
        min_length=1,
        title="App (client) ID",
        description="The Microsoft App ID shown under Configuration on your Azure Bot resource.",
    )
    app_password: str = Field(
        min_length=1,
        title="Client secret",
        description=(
            "Create it in the linked app registration under Certificates & secrets. Copy the secret Value, not "
            "the Secret ID; the Value is shown only once."
        ),
    )
    tenant_id: str = Field(
        min_length=1,
        title="Tenant ID",
        description="The Directory (tenant) ID from Microsoft Entra ID → Overview.",
    )


class TeamsPlatformPlugin(PlatformPlugin):
    key = "teams"
    display_name = "Microsoft Teams"
    setup_hint = (
        "Credentials\n"
        "• Create an Azure Bot resource in the Azure Portal, then open Configuration and copy the Microsoft App ID.\n"
        "• Open the linked app registration → Certificates & secrets → New client secret. Copy the secret Value "
        "immediately; it is masked once you leave the page, and the Secret ID is not the password.\n"
        "• Copy the Directory (tenant) ID from Microsoft Entra ID → Overview.\n\n"
        "Teams setup\n"
        "• In the Azure Bot resource, open Channels and enable Microsoft Teams.\n"
        "• After saving this connection, paste its webhook URL into the Azure Bot's Configuration → Messaging "
        "endpoint. The endpoint must be reachable from the public internet or Microsoft cannot deliver messages.\n"
        "• Install the bot in Teams for the chats and teams it should serve.\n\n"
        "Connection settings\n"
        "• Direct messages default to Off; set Direct messages to Open or Allowlist when DMs are needed.\n"
        "• Teams delivers channel and group-chat messages only when the bot is @mentioned.\n"
        "• Allowed DM senders use the sender's Microsoft Entra object ID; Allowed channels use the Teams channel "
        "conversation ID, which looks like 19:....@thread.tacv2."
    )
    capabilities = frozenset(
        {
            PlatformCapability.WEBHOOK_INGRESS,
            PlatformCapability.MENTIONS,
            PlatformCapability.THREADS,
        }
    )
    settings_model = TeamsSettings
    credentials_model = TeamsCredentials
    credential_uniqueness_scope = CredentialUniquenessScope.GLOBAL

    def __init__(self, config: TeamsValidationConfig) -> None:
        self._skip_validation = config.skip_teams_token_validation

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        assert isinstance(credentials, TeamsCredentials)
        if self._skip_validation:
            return "validation-skipped"
        acquire_token(credentials.tenant_id, credentials.app_id, credentials.app_password)
        return credentials.app_id

    def fingerprint_material(self, credentials: PlatformCredentials) -> str:
        assert isinstance(credentials, TeamsCredentials)
        return f"{credentials.tenant_id}:{credentials.app_id}"

    def verify_webhook(
        self,
        credentials: PlatformCredentials,
        payload: dict[str, Any],
        authorization: str,
    ) -> None:
        assert isinstance(credentials, TeamsCredentials)
        del payload
        verify_inbound_jwt(authorization, credentials.app_id)

    def send(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelope: OutboundCommunicationEnvelope,
    ) -> str:
        assert isinstance(credentials, TeamsCredentials)
        metadata = envelope.provider_metadata
        service_url = str(metadata.get("service_url") or "")
        if not service_url:
            raise ValueError("Teams reply is missing the serviceUrl captured from its inbound activity")

        # The thread lives in the conversation id, so the stored raw value is
        # sent whole rather than the stripped location id.
        conversation_id = str(metadata.get("conversation_id") or envelope.location.id)
        activity: dict[str, Any] = {
            "type": "message",
            "text": envelope.text,
            "conversation": {"id": conversation_id},
        }
        if metadata.get("recipient_id"):
            activity["from"] = {"id": str(metadata["recipient_id"])}
        if metadata.get("from_id"):
            activity["recipient"] = {"id": str(metadata["from_id"])}
        if envelope.reply_to_provider_message_id:
            activity["replyToId"] = envelope.reply_to_provider_message_id

        token = acquire_token(credentials.tenant_id, credentials.app_id, credentials.app_password)
        return send_activity(service_url, conversation_id, activity, token)

    def normalize_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> list[NormalizedCommunicationEnvelope]:
        assert isinstance(settings, TeamsSettings)
        if payload.get("type") != "message":
            return []

        conversation = payload.get("conversation")
        sender = payload.get("from")
        if not isinstance(conversation, dict) or not isinstance(sender, dict):
            return []

        bot_id = str((payload.get("recipient") or {}).get("id") or "")
        sender_id = str(sender.get("aadObjectId") or sender.get("id") or "")
        if not sender_id or (bot_id and sender_id == bot_id):
            return []

        raw_conversation_id = str(conversation.get("id") or "")
        message_id = str(payload.get("id") or "")
        if not raw_conversation_id or not message_id:
            return []

        # Teams appends ";messageid=<id>" to a channel conversation id for thread
        # replies. Left in place it would split one channel into a conversation
        # per thread, so the suffix becomes the thread id instead.
        conversation_id, _, thread_suffix = raw_conversation_id.partition(_MESSAGE_ID_SEPARATOR)
        is_dm = conversation.get("conversationType") == _PERSONAL_CONVERSATION_TYPE

        if is_dm:
            if settings.dm_policy == "off":
                return []
            if settings.dm_policy == "allowlist" and sender_id not in settings.dm_user_ids:
                return []
        elif settings.group_policy == "allowlist" and conversation_id not in settings.channel_ids:
            return []

        thread_id = thread_suffix or str(payload.get("replyToId") or "") or None
        sender_name = str(sender.get("name") or "") or None
        # Teams omits channelData.channel.name on ordinary messages, so a team
        # channel has no name to show without Microsoft Graph.
        display_name = str(conversation.get("name") or "") or (sender_name if is_dm else None)

        return [
            NormalizedCommunicationEnvelope(
                provider_message_id=message_id,
                occurred_at=_occurred_at(payload.get("timestamp")),
                location=ConversationLocation(
                    id=conversation_id,
                    type="DM" if is_dm else "CHANNEL",
                    display_name=display_name,
                    thread_id=thread_id,
                ),
                sender=CommunicationSender(id=sender_id, display_name=sender_name),
                text=_without_own_mention(str(payload.get("text") or ""), payload.get("entities"), bot_id),
                mentions=_mentioned_ids(payload.get("entities")),
                provider_metadata={
                    "service_url": str(payload.get("serviceUrl") or ""),
                    "conversation_id": raw_conversation_id,
                    "from_id": str(sender.get("id") or ""),
                    "recipient_id": bot_id,
                    "tenant_id": str(((payload.get("channelData") or {}).get("tenant") or {}).get("id") or ""),
                },
            )
        ]


def _occurred_at(raw: Any) -> datetime:
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw).astimezone(UTC)
        except ValueError:
            logger.warning("Unparseable Teams activity timestamp: %s", raw)
    return datetime.now(UTC)


def _without_own_mention(text: str, entities: Any, bot_id: str) -> str:
    """Remove the agent's own `<at>Name</at>` markup, leaving other mentions intact.

    Teams delivers channel messages only when the agent is mentioned, so the
    markup is on every one of them. Left in, the agent reads its own display
    name as a third party. Mentions of other people can be meaningful input and
    are preserved.
    """
    if not isinstance(entities, list) or not bot_id:
        return text
    for entity in entities:
        if not isinstance(entity, dict) or entity.get("type") != "mention":
            continue
        target = entity.get("mentioned")
        markup = entity.get("text")
        if isinstance(target, dict) and str(target.get("id") or "") == bot_id and markup:
            text = text.replace(str(markup), "")
    return text.strip()


def _mentioned_ids(entities: Any) -> list[str]:
    if not isinstance(entities, list):
        return []
    mentioned: list[str] = []
    for entity in entities:
        if not isinstance(entity, dict) or entity.get("type") != "mention":
            continue
        target = entity.get("mentioned")
        if isinstance(target, dict) and target.get("id"):
            mentioned.append(str(target["id"]))
    return list(dict.fromkeys(mentioned))
