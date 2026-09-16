import logging
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from pydantic import Field

from api.domains.communications.models import (
    CommunicationPolicyDisposition,
    CommunicationSender,
    ConversationLocation,
    CredentialUniquenessScope,
    NormalizedCommunicationEnvelope,
    OutboundCommunicationEnvelope,
    PlatformCapability,
)
from api.domains.communications.plugins.base import (
    InboundAdmissionResult,
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
    provider_idempotency_key,
)
from api.infrastructure.msteams.client import (
    TeamsAuthError,
    acquire_token,
    list_team_channels,
    send_activity,
    verify_inbound_jwt,
)
from api.infrastructure.msteams.manifest import build_app_package as build_teams_app_package

logger = logging.getLogger(__name__)

_MESSAGE_ID_SEPARATOR = ";messageid="
_PERSONAL_CONVERSATION_TYPE = "personal"


class TeamsValidationConfig(Protocol):
    skip_teams_token_validation: bool
    teams_publisher_name: str
    teams_publisher_website_url: str
    teams_privacy_url: str
    teams_terms_url: str


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
        "## Create credentials\n\n"
        "1. Create an Azure Bot resource in the Azure Portal, then open **Configuration** and copy the Microsoft App ID.\n"
        "2. Open **Manage passwords → Certificates & secrets → New client secret**. Copy the secret **Value** immediately; "
        "it is masked once you leave the page, and the Secret ID is not the password.\n"
        "3. Copy the Directory (tenant) ID from **Microsoft Entra ID → Overview**.\n\n"
        "## Configure Teams\n\n"
        "1. In the Azure Bot resource, open **Channels** and enable Microsoft Teams.\n"
        "2. After saving this Connection, paste its webhook URL into the Azure Bot's **Configuration → Messaging endpoint**. "
        "The endpoint must be reachable from the public internet.\n"
        "3. Install the bot in Teams for the chats and teams it should serve.\n\n"
        "## Set Connection access\n\n"
        "1. Direct messages default to Off; set Direct messages to Open or Allowlist when DMs are needed.\n"
        "2. Teams delivers channel and group-chat messages only when the bot is @mentioned.\n"
        "3. Allowed DM senders use the sender's Microsoft Entra object ID; Allowed channels use the Teams channel "
        "conversation ID, which looks like `19:....@thread.tacv2`."
    )
    post_setup_hint = (
        "## Finish setup\n\n"
        "1. Paste the webhook URL above into the Azure Bot's **Configuration → Messaging endpoint**, then Apply. The endpoint "
        "must be reachable from the public internet.\n"
        "2. Download the app package and upload it in Teams: **Apps → Manage your apps → Upload a custom app**. Add it to "
        "every team and chat this Agent should serve.\n"
        "3. Re-upload the package after renaming the Agent to refresh how it appears in Teams."
    )
    capabilities = frozenset(
        {
            PlatformCapability.APPLICATION_PROVISIONING,
            PlatformCapability.SUPERVISED_INGRESS,
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
        self._publisher_name = config.teams_publisher_name
        self._website_url = config.teams_publisher_website_url
        self._privacy_url = config.teams_privacy_url
        self._terms_url = config.teams_terms_url

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        assert isinstance(credentials, TeamsCredentials)
        if self._skip_validation:
            return "validation-skipped"
        acquire_token(credentials.tenant_id, credentials.app_id, credentials.app_password)
        return credentials.app_id

    def fingerprint_material(self, credentials: PlatformCredentials) -> str:
        assert isinstance(credentials, TeamsCredentials)
        return f"{credentials.tenant_id}:{credentials.app_id}"

    def build_app_package(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        *,
        connection_id: UUID,
        display_name: str,
    ) -> tuple[str, bytes]:
        del settings
        assert isinstance(credentials, TeamsCredentials)
        return build_teams_app_package(
            connection_id=connection_id,
            app_id=credentials.app_id,
            display_name=display_name,
            publisher_name=self._publisher_name,
            website_url=self._website_url,
            privacy_url=self._privacy_url,
            terms_url=self._terms_url,
        )

    def verify_webhook(
        self,
        credentials: PlatformCredentials,
        payload: dict[str, Any],
        authorization: str,
    ) -> None:
        assert isinstance(credentials, TeamsCredentials)
        try:
            verify_inbound_jwt(
                authorization,
                credentials.app_id,
                service_url=str(payload.get("serviceUrl") or ""),
            )
        except TeamsAuthError as exc:
            raise PermissionError(str(exc)) from exc

    def send(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelope: OutboundCommunicationEnvelope,
        *,
        idempotency_key: str,
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
        return send_activity(
            service_url,
            conversation_id,
            activity,
            token,
            idempotency_key=provider_idempotency_key(idempotency_key),
        )

    def enrich_inbound(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelopes: list[NormalizedCommunicationEnvelope],
    ) -> list[NormalizedCommunicationEnvelope]:
        del settings
        assert isinstance(credentials, TeamsCredentials)
        return [self._enrich_envelope(credentials, envelope) for envelope in envelopes]

    def _enrich_envelope(
        self,
        credentials: TeamsCredentials,
        envelope: NormalizedCommunicationEnvelope,
    ) -> NormalizedCommunicationEnvelope:
        location = envelope.location
        if location.type != "CHANNEL" or location.display_name:
            return envelope

        service_url = str(envelope.provider_metadata.get("service_url") or "")
        team_id = str(envelope.provider_metadata.get("team_id") or "")
        if not service_url or not team_id:
            return envelope

        try:
            token = acquire_token(credentials.tenant_id, credentials.app_id, credentials.app_password)
            channels = list_team_channels(service_url, team_id, token)
        except Exception as exc:
            logger.warning(
                "Teams inbound enrichment resolve channel name failed for message %s (%s)",
                envelope.provider_message_id,
                type(exc).__name__,
            )
            return envelope

        if location.id not in channels:
            return envelope
        # Teams reports the default General channel with a null name so callers
        # can localize it; its channel id always equals the team id.
        name = channels[location.id] or ("General" if location.id == team_id else None)
        if not name:
            return envelope
        return envelope.model_copy(update={"location": location.model_copy(update={"display_name": name})})

    def normalize_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> InboundAdmissionResult:
        assert isinstance(settings, TeamsSettings)
        if payload.get("type") != "message":
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)

        conversation = payload.get("conversation")
        sender = payload.get("from")
        if not isinstance(conversation, dict) or not isinstance(sender, dict):
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)

        bot_id = str((payload.get("recipient") or {}).get("id") or "")
        sender_id = str(sender.get("aadObjectId") or sender.get("id") or "")
        if not sender_id:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        if bot_id and sender_id == bot_id:
            return InboundAdmissionResult(CommunicationPolicyDisposition.BOT_IGNORED)

        raw_conversation_id = str(conversation.get("id") or "")
        message_id = str(payload.get("id") or "")
        if not raw_conversation_id or not message_id:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)

        # Teams appends ";messageid=<id>" to a channel conversation id for thread
        # replies. Left in place it would split one channel into a conversation
        # per thread, so the suffix becomes the thread id instead.
        conversation_id, _, thread_suffix = raw_conversation_id.partition(_MESSAGE_ID_SEPARATOR)
        is_dm = conversation.get("conversationType") == _PERSONAL_CONVERSATION_TYPE

        if is_dm:
            if settings.dm_policy == "off":
                return InboundAdmissionResult(CommunicationPolicyDisposition.USER_DENIED)
            if settings.dm_policy == "allowlist" and sender_id not in settings.dm_user_ids:
                return InboundAdmissionResult(CommunicationPolicyDisposition.USER_DENIED)
        elif settings.group_policy == "allowlist" and conversation_id not in settings.channel_ids:
            return InboundAdmissionResult(CommunicationPolicyDisposition.CHANNEL_DENIED)

        thread_id = thread_suffix or str(payload.get("replyToId") or "") or None
        sender_name = str(sender.get("name") or "") or None
        # Teams omits channelData.channel.name on ordinary messages, so a team
        # channel has no name to show without Microsoft Graph.
        display_name = str(conversation.get("name") or "") or (sender_name if is_dm else None)

        envelope = NormalizedCommunicationEnvelope(
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
                "team_id": str(((payload.get("channelData") or {}).get("team") or {}).get("id") or ""),
                "tenant_id": str(((payload.get("channelData") or {}).get("tenant") or {}).get("id") or ""),
            },
        )
        return InboundAdmissionResult(CommunicationPolicyDisposition.ACCEPTED, (envelope,))


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
