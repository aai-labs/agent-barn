import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from pydantic import Field
from websockets.asyncio.client import connect

from api.domains.communications.models import (
    ApprovalRequest,
    CommunicationPolicyDisposition,
    CommunicationSender,
    ConversationLocation,
    CredentialUniquenessScope,
    NormalizedCommunicationEnvelope,
    OutboundCommunicationEnvelope,
    PlatformCapability,
)
from api.domains.communications.plugins.approvals import (
    APPROVAL_COMPONENT_MAX_CHARS,
    APPROVAL_METADATA_KEY,
    SYNTHESIZED_MESSAGE_PREFIX,
    decode_approval_component,
    encode_approval_component,
    is_approval_component,
    is_synthesized_message_id,
)
from api.domains.communications.plugins.base import (
    InboundAdmissionResult,
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
    ProcessingFeedbackContext,
    best_effort_failure_notice,
    provider_idempotency_key,
)
from api.infrastructure.discord.client import DiscordClient

logger = logging.getLogger(__name__)

_INSTALL_OAUTH_SCOPES = "bot%20applications.commands"
_INSTALL_PERMISSIONS = 274878286912
_CONTENT_LIMIT = 2_000
_BUTTONS_PER_ROW = 5
_BUTTON_LABEL_LIMIT = 80
_ACTION_ROW_TYPE = 1
_BUTTON_TYPE = 2
_SECONDARY_BUTTON_STYLE = 2
_DANGER_BUTTON_STYLE = 4
_MESSAGE_COMPONENT_INTERACTION = 3
_INTERACTION_CALLBACK_URL = "https://discord.com/api/v10/interactions/{interaction_id}/{token}/callback"
_INTERACTION_ACK_TIMEOUT_SECONDS = 5
_DEFERRED_UPDATE_CALLBACK = {"type": 6}
_CLEAR_COMPONENTS_CALLBACK = {"type": 7, "data": {"components": []}}


def _approval_content(approval: ApprovalRequest) -> str:
    fallback = f"\nOr reply to your original request with one of: {', '.join(approval.choices)}"
    fenced = approval.command.replace("```", "`\u200b``")
    budget = _CONTENT_LIMIT - len("```\n\n```") - len(fallback) - 40
    if len(fenced) > budget:
        hidden = len(fenced) - budget
        fenced = f"{fenced[:budget]}\n[{hidden} more characters not shown]"
    return f"```\n{fenced}\n```{fallback}"


def _approval_buttons(approval: ApprovalRequest, thread_id: str) -> list[dict[str, Any]] | None:
    buttons: list[dict[str, Any]] = []
    for choice in approval.choices:
        custom_id = encode_approval_component(thread_id, approval.approval_id, choice)
        if len(custom_id) > APPROVAL_COMPONENT_MAX_CHARS:
            return None
        buttons.append(
            {
                "type": _BUTTON_TYPE,
                "style": _DANGER_BUTTON_STYLE if choice == "deny" else _SECONDARY_BUTTON_STYLE,
                "label": approval.choice_labels.get(choice, choice)[:_BUTTON_LABEL_LIMIT],
                "custom_id": custom_id,
            }
        )
    return [
        {"type": _ACTION_ROW_TYPE, "components": buttons[start : start + _BUTTONS_PER_ROW]}
        for start in range(0, len(buttons), _BUTTONS_PER_ROW)
    ]


def _approval_components(approval: ApprovalRequest, thread_id: str) -> list[dict[str, Any]] | None:
    rows = _approval_buttons(approval, thread_id) or _approval_buttons(approval, "")
    if rows is None:
        logger.warning(
            "Discord approval %s offers no buttons: its identifier exceeds %s characters",
            approval.approval_id,
            APPROVAL_COMPONENT_MAX_CHARS,
        )
    return rows


class DiscordValidationConfig(Protocol):
    skip_discord_token_validation: bool


class DiscordSettings(PlatformSettings):
    allowed_channel_ids: list[str] = Field(
        default_factory=list,
        title="Allowed channels",
        description="Channel IDs this agent may respond in. A thread inherits its parent channel's access.",
    )
    allowed_user_ids: list[str] = Field(
        default_factory=list,
        title="Allowed users",
        description="User IDs allowed to interact with this agent (combined with Allowed roles).",
    )
    allowed_role_ids: list[str] = Field(
        default_factory=list,
        title="Allowed roles",
        description="Members with any of these Discord role IDs may interact with this agent.",
    )
    allow_all_users: bool = Field(
        default=False,
        title="Allow all users",
        description=(
            "Allow messages from every Discord user in DMs and server channels. "
            "When disabled, the native Discord adapter uses the configured user, role, and channel allowlists."
        ),
    )
    require_mention: bool = Field(
        default=True, title="Require @mention", description="Only respond in servers when directly @mentioned."
    )
    home_channel_id: str | None = Field(
        default=None, title="Alert channel", description="Optional channel ID for scheduled or proactive updates."
    )


class DiscordCredentials(PlatformCredentials):
    bot_token: str = Field(
        min_length=1,
        title="Bot token",
        description=(
            "From Developer Portal → Applications → your app → Bot → Token. Paste the bot token, not the Application "
            "ID, public key, client secret, or invite URL."
        ),
    )


class DiscordPlatformPlugin(PlatformPlugin):
    key = "discord"
    display_name = "Discord"
    schema_version = 2
    setup_hint = (
        "## Create and configure a bot\n\n"
        "1. In [Discord Developer Portal](https://discord.com/developers/applications), create or open an Application and "
        "open its **Bot** page. Reset/copy the Token; do not use the Application ID, public key, client secret, or an "
        "OAuth invite URL.\n"
        "2. Under **Bot → Privileged Gateway Intents**, enable **Message Content Intent**. Enable **Server Members Intent** "
        "too when you want the Connection editor to suggest server members.\n\n"
        "## Invite the bot\n\n"
        "1. After saving this Connection, use **Install bot to server** on its card to add the bot to each server "
        "with the recommended permissions.\n"
        "2. To invite manually instead, open **OAuth2 → URL Generator**, choose the bot scope, and grant **View "
        "Channels**, **Send Messages**, and **Read Message History**; also grant **Send Messages in Threads** when "
        "threads are used.\n\n"
        "## Finish the Connection\n\n"
        "1. Paste the Bot Token into this Connection and save it.\n"
        "2. The bot must view every allowed channel. Enable **Developer Mode** to copy channel, user, and role IDs.\n"
        "3. By default the bot denies users not covered by an allowed user, role, or channel. Enable **Allow all users** "
        "only when anyone may use the bot. When **Require @mention** is on, people must mention the bot in server messages."
    )
    capabilities = frozenset(
        {
            PlatformCapability.DIRECTORY_DISCOVERY,
            PlatformCapability.INSTALL_LINK,
            PlatformCapability.ATTACHMENTS,
            PlatformCapability.SUPERVISED_INGRESS,
            PlatformCapability.MENTIONS,
            PlatformCapability.PROCESSING_FEEDBACK,
            PlatformCapability.THREADS,
        }
    )
    settings_model = DiscordSettings
    credentials_model = DiscordCredentials
    credential_uniqueness_scope = CredentialUniquenessScope.GLOBAL

    def __init__(self, config: DiscordValidationConfig) -> None:
        self._skip_validation = config.skip_discord_token_validation

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        assert isinstance(credentials, DiscordCredentials)
        if self._skip_validation:
            return "validation-skipped"
        bot = DiscordClient(credentials.bot_token).get_current_bot()
        username = str(bot.get("username") or "")
        discriminator = str(bot.get("discriminator") or "")
        return f"@{username}#{discriminator}" if discriminator and discriminator != "0" else f"@{username}"

    def build_install_link(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str:
        del settings
        assert isinstance(credentials, DiscordCredentials)
        application = DiscordClient(credentials.bot_token).get_current_application()
        return (
            "https://discord.com/oauth2/authorize"
            f"?client_id={application['id']}&scope={_INSTALL_OAUTH_SCOPES}&permissions={_INSTALL_PERMISSIONS}"
        )

    def fingerprint_material(self, credentials: PlatformCredentials) -> str:
        assert isinstance(credentials, DiscordCredentials)
        return credentials.bot_token

    def list_directory_entries(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        *,
        kind: str,
        search: str | None = None,
        guild_id: str | None = None,
    ) -> list[dict[str, str | None]]:
        del settings
        assert isinstance(credentials, DiscordCredentials)
        client = DiscordClient(credentials.bot_token)
        if kind == "guilds":
            entries = client.list_guilds()
            prefix = ""
        elif kind == "channels" and guild_id:
            entries = client.list_guild_channels(guild_id)
            prefix = "#"
        elif kind == "users" and guild_id:
            entries = client.list_guild_members(guild_id)
            prefix = ""
        elif kind == "roles" and guild_id:
            entries = client.list_guild_roles(guild_id)
            prefix = "@"
        else:
            raise ValueError("Choose a Discord server before browsing channels, users, or roles")
        query = search.lower() if search else ""
        return [
            {"id": entry["id"], "label": f"{prefix}{entry['name']}", "detail": None}
            for entry in entries
            if not query or query in entry["id"].lower() or query in entry["name"].lower()
        ]

    def send(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelope: OutboundCommunicationEnvelope,
        *,
        idempotency_key: str,
    ) -> str:
        assert isinstance(credentials, DiscordCredentials)
        content = _approval_content(envelope.approval) if envelope.approval else envelope.text
        components = (
            _approval_components(envelope.approval, envelope.location.thread_id or "") if envelope.approval else None
        )
        reply_to_id = envelope.reply_to_provider_message_id
        return DiscordClient(credentials.bot_token).send_message(
            envelope.location.id,
            content,
            reply_to_id=None if is_synthesized_message_id(reply_to_id) else reply_to_id,
            idempotency_key=provider_idempotency_key(idempotency_key),
            **({"components": components} if components else {}),
        )

    def _location_disposition(
        self,
        settings: DiscordSettings,
        *,
        channel_id: str,
    ) -> CommunicationPolicyDisposition | None:
        if settings.allow_all_users:
            return None
        if settings.allowed_channel_ids and channel_id not in settings.allowed_channel_ids:
            return CommunicationPolicyDisposition.CHANNEL_DENIED
        if not (settings.allowed_channel_ids or settings.allowed_user_ids or settings.allowed_role_ids):
            return CommunicationPolicyDisposition.USER_DENIED
        return None

    def _member_disposition(
        self,
        settings: DiscordSettings,
        *,
        sender_id: str,
        roles: list[str],
    ) -> CommunicationPolicyDisposition | None:
        if settings.allow_all_users:
            return None
        if (
            (settings.allowed_user_ids or settings.allowed_role_ids)
            and sender_id not in settings.allowed_user_ids
            and not set(roles) & set(settings.allowed_role_ids)
        ):
            return CommunicationPolicyDisposition.USER_DENIED
        return None

    def _dm_disposition(self, settings: DiscordSettings, sender_id: str) -> CommunicationPolicyDisposition | None:
        # Hermes applies its user allowlist to both DMs and servers, but only
        # applies role allowlists to DMs with an additional guild setting that
        # Agent Barn does not expose. Mirror the portable subset exactly.
        if not settings.allow_all_users and sender_id not in settings.allowed_user_ids:
            return CommunicationPolicyDisposition.USER_DENIED
        return None

    def _normalize_interaction(
        self,
        settings: DiscordSettings,
        payload: dict[str, Any],
    ) -> InboundAdmissionResult:
        raw_event = payload.get("d")
        if not isinstance(raw_event, dict):
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        event: dict[str, Any] = raw_event
        if event.get("type") != _MESSAGE_COMPONENT_INTERACTION:
            return InboundAdmissionResult(CommunicationPolicyDisposition.EVENT_IGNORED)
        data = event.get("data")
        custom_id = str(data.get("custom_id") or "") if isinstance(data, dict) else ""
        if not is_approval_component(custom_id):
            return InboundAdmissionResult(CommunicationPolicyDisposition.EVENT_IGNORED)
        thread_id, approval_id, choice = decode_approval_component(custom_id)
        if not approval_id or not choice:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)

        interaction_id = str(event.get("id") or "")
        channel_id = str(event.get("channel_id") or "")
        guild_id = str(event.get("guild_id") or "")
        is_dm = not guild_id
        raw_member = event.get("member")
        member: dict[str, Any] = raw_member if isinstance(raw_member, dict) else {}
        raw_clicker = event.get("user") if is_dm else member.get("user")
        if not isinstance(raw_clicker, dict):
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        clicker: dict[str, Any] = raw_clicker
        sender_id = str(clicker.get("id") or "")
        if not interaction_id or not channel_id or not sender_id:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)

        bot_user_id = str(payload.get("agentbarn_bot_user_id") or "")
        if clicker.get("bot") or (bot_user_id and sender_id == bot_user_id):
            return InboundAdmissionResult(CommunicationPolicyDisposition.BOT_IGNORED)

        if is_dm:
            denied = self._dm_disposition(settings, sender_id)
        else:
            roles = member.get("roles", [])
            if not isinstance(roles, list):
                return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
            denied = self._location_disposition(settings, channel_id=channel_id) or (
                self._member_disposition(settings, sender_id=sender_id, roles=[str(role) for role in roles])
            )
        if denied is not None:
            return InboundAdmissionResult(denied)

        raw_clicked = event.get("message")
        clicked: dict[str, Any] = raw_clicked if isinstance(raw_clicked, dict) else {}
        author = clicked.get("author")
        posted_by = str(author.get("id") or "") if isinstance(author, dict) else ""
        if not bot_user_id or posted_by != bot_user_id:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MENTION_REQUIRED)

        if not thread_id:
            reference = clicked.get("message_reference")
            thread_id = str(reference.get("message_id") or "") if isinstance(reference, dict) else ""
            if not thread_id:
                return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)

        return InboundAdmissionResult(
            CommunicationPolicyDisposition.ACCEPTED,
            (
                NormalizedCommunicationEnvelope(
                    provider_message_id=f"{SYNTHESIZED_MESSAGE_PREFIX}{interaction_id}",
                    occurred_at=datetime.now(UTC),
                    location=ConversationLocation(
                        id=channel_id,
                        type="DM" if is_dm else "CHANNEL",
                        thread_id=thread_id or None,
                    ),
                    sender=CommunicationSender(
                        id=sender_id,
                        display_name=str(
                            member.get("nick") or clicker.get("global_name") or clicker.get("username") or ""
                        )
                        or None,
                    ),
                    text=choice,
                    provider_metadata={APPROVAL_METADATA_KEY: approval_id, "guild_id": guild_id},
                ),
            ),
        )

    def processing_feedback(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        context: ProcessingFeedbackContext,
    ) -> None:
        del settings
        assert isinstance(credentials, DiscordCredentials)
        best_effort_failure_notice(
            context,
            lambda text, idempotency_key: DiscordClient(credentials.bot_token).send_message(
                context.location.id,
                text,
                reply_to_id=context.provider_message_id,
                idempotency_key=idempotency_key,
            ),
            target=f"Discord channel {context.location.id}",
            logger=logger,
        )

    def normalize_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> InboundAdmissionResult:
        assert isinstance(settings, DiscordSettings)
        if payload.get("t") == "INTERACTION_CREATE":
            return self._normalize_interaction(settings, payload)
        event = payload.get("d") if payload.get("t") == "MESSAGE_CREATE" else payload
        if not isinstance(event, dict):
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        raw_author = event.get("author")
        if not isinstance(raw_author, dict):
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        author: dict[str, Any] = raw_author
        if author.get("bot"):
            return InboundAdmissionResult(CommunicationPolicyDisposition.BOT_IGNORED)
        message_id = str(event.get("id") or "")
        channel_id = str(event.get("channel_id") or "")
        sender_id = str(author.get("id") or "")
        guild_id = str(event.get("guild_id") or "")
        is_dm = not guild_id
        if not message_id or not channel_id:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        if is_dm:
            dm_denied = self._dm_disposition(settings, sender_id)
            if dm_denied is not None:
                return InboundAdmissionResult(dm_denied)
        else:
            location_denied = self._location_disposition(settings, channel_id=channel_id)
            if location_denied is not None:
                return InboundAdmissionResult(location_denied)
            raw_member = event.get("member")
            if raw_member is not None and not isinstance(raw_member, dict):
                return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
            member_for_policy: dict[str, Any] = raw_member if isinstance(raw_member, dict) else {}
            roles = member_for_policy.get("roles", [])
            if not isinstance(roles, list):
                return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
            member_denied = self._member_disposition(
                settings,
                sender_id=sender_id,
                roles=[str(role) for role in roles],
            )
            if member_denied is not None:
                return InboundAdmissionResult(member_denied)
            if settings.require_mention:
                bot_user_id = str(payload.get("agentbarn_bot_user_id") or "")
                raw_mentions = event.get("mentions", [])
                if not isinstance(raw_mentions, list):
                    return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
                mentioned_ids = {
                    str(mention.get("id"))
                    for mention in raw_mentions
                    if isinstance(mention, dict) and mention.get("id")
                }
                if not bot_user_id or bot_user_id not in mentioned_ids:
                    return InboundAdmissionResult(CommunicationPolicyDisposition.MENTION_REQUIRED)
        raw_time = event.get("timestamp")
        try:
            occurred_at = datetime.fromisoformat(str(raw_time)) if raw_time else datetime.now(UTC)
        except (TypeError, ValueError) as _:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        raw_member = event.get("member")
        member: dict[str, Any] = raw_member if isinstance(raw_member, dict) else {}
        raw_reference = event.get("message_reference")
        reference: dict[str, Any] = raw_reference if isinstance(raw_reference, dict) else {}
        return InboundAdmissionResult(
            CommunicationPolicyDisposition.ACCEPTED,
            (
                NormalizedCommunicationEnvelope(
                    provider_message_id=message_id,
                    occurred_at=occurred_at,
                    location=ConversationLocation(
                        id=channel_id,
                        type="DM" if is_dm else "CHANNEL",
                        thread_id=str(reference.get("message_id") or message_id),
                    ),
                    sender=CommunicationSender(
                        id=sender_id or None,
                        display_name=str(
                            member.get("nick") or author.get("global_name") or author.get("username") or ""
                        )
                        or None,
                    ),
                    text=str(event.get("content") or ""),
                    reply_to_provider_message_id=str(reference.get("message_id") or "") or None,
                    provider_metadata={"guild_id": guild_id},
                ),
            ),
        )

    def enrich_inbound(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelopes: list[NormalizedCommunicationEnvelope],
    ) -> list[NormalizedCommunicationEnvelope]:
        del settings
        assert isinstance(credentials, DiscordCredentials)
        client = DiscordClient(credentials.bot_token)
        return [self._enrich_envelope(client, envelope) for envelope in envelopes]

    def _enrich_envelope(
        self,
        client: DiscordClient,
        envelope: NormalizedCommunicationEnvelope,
    ) -> NormalizedCommunicationEnvelope:
        sender = envelope.sender
        if sender.id and not sender.display_name:
            name = self._safe_lookup(
                "resolve sender name",
                envelope,
                lambda: client.get_user_display_name(sender.id or ""),
            )
            if name:
                sender = sender.model_copy(update={"display_name": name})

        location = envelope.location
        if not location.display_name:
            name = self._safe_lookup(
                "resolve channel name",
                envelope,
                lambda: client.get_channel_display_name(location.id),
            )
            if name:
                location = location.model_copy(update={"display_name": name})

        if sender is envelope.sender and location is envelope.location:
            return envelope
        return envelope.model_copy(update={"sender": sender, "location": location})

    @staticmethod
    def _safe_lookup(
        action: str,
        envelope: NormalizedCommunicationEnvelope,
        callback: Callable[[], str | None],
    ) -> str | None:
        try:
            return callback()
        except Exception as exc:
            logger.warning(
                "Discord inbound enrichment %s failed for message %s (%s)",
                action,
                envelope.provider_message_id,
                type(exc).__name__,
            )
            return None

    async def _acknowledge_interaction(self, settings: PlatformSettings, message: dict[str, Any]) -> None:
        event = message.get("d")
        if not isinstance(event, dict):
            return
        interaction_id = str(event.get("id") or "")
        token = str(event.get("token") or "")
        if not interaction_id or not token:
            return
        try:
            admitted = self.normalize_inbound(settings, message).disposition == CommunicationPolicyDisposition.ACCEPTED
            async with httpx.AsyncClient(timeout=_INTERACTION_ACK_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    _INTERACTION_CALLBACK_URL.format(interaction_id=interaction_id, token=token),
                    json=_CLEAR_COMPONENTS_CALLBACK if admitted else _DEFERRED_UPDATE_CALLBACK,
                )
                response.raise_for_status()
        except Exception as exc:
            logger.warning("Discord interaction acknowledgement failed (%s)", type(exc).__name__)

    async def run_ingress(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        emit: Callable[[dict[str, Any]], Awaitable[None]],
        connected: Callable[[], Awaitable[None]],
    ) -> None:
        assert isinstance(credentials, DiscordCredentials)
        gateway = await asyncio.to_thread(DiscordClient(credentials.bot_token).get_gateway_url)
        url = f"{gateway.rstrip('/')}?v=10&encoding=json"
        async with connect(url, open_timeout=15, ping_interval=None) as socket:
            hello = json.loads(await socket.recv())
            if hello.get("op") != 10:
                raise RuntimeError("Discord Gateway did not send Hello")
            heartbeat_seconds = float(hello["d"]["heartbeat_interval"]) / 1000
            await socket.send(
                json.dumps(
                    {
                        "op": 2,
                        "d": {
                            "token": credentials.bot_token,
                            "intents": 37377,
                            "properties": {
                                "os": "linux",
                                "browser": "agent-barn",
                                "device": "agent-barn",
                            },
                        },
                    }
                )
            )
            sequence: int | None = None
            bot_user_id: str | None = None
            while True:
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=heartbeat_seconds)
                except TimeoutError:
                    await socket.send(json.dumps({"op": 1, "d": sequence}))
                    continue
                message = json.loads(raw)
                if isinstance(message.get("s"), int):
                    sequence = message["s"]
                if message.get("op") == 1:
                    await socket.send(json.dumps({"op": 1, "d": sequence}))
                    continue
                if message.get("op") in (7, 9):
                    raise RuntimeError("Discord Gateway requested reconnect")
                if message.get("t") == "READY":
                    bot_user_id = str(message.get("d", {}).get("user", {}).get("id") or "")
                    await connected()
                    continue
                if message.get("t") == "INTERACTION_CREATE" and bot_user_id:
                    message["agentbarn_bot_user_id"] = bot_user_id
                    await self._acknowledge_interaction(settings, message)
                    await emit(message)
                    continue
                if message.get("t") == "MESSAGE_CREATE" and bot_user_id:
                    message["agentbarn_bot_user_id"] = bot_user_id
                    await emit(message)
