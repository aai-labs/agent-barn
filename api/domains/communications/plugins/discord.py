import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import Field
from websockets.asyncio.client import connect

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
)
from api.infrastructure.discord.client import DiscordClient

logger = logging.getLogger(__name__)


class DiscordValidationConfig(Protocol):
    skip_discord_token_validation: bool


class DiscordSettings(PlatformSettings):
    guild_ids: list[str] = Field(
        default_factory=list,
        title="Allowed servers",
        description="Discord server (guild) IDs this agent may respond in. Used when Channel access is Allowlist.",
    )
    allowed_channel_ids: list[str] = Field(
        default_factory=list,
        title="Allowed channels",
        description="Channel IDs this agent may read and post in. Leave empty to allow any channel in an allowed server.",
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
    group_policy: str = Field(
        default="allowlist",
        pattern="^(open|allowlist)$",
        title="Channel access",
        description="Open responds in any server it's added to. Allowlist restricts it to Allowed servers.",
    )
    dm_policy: str = Field(
        default="off",
        pattern="^(off|open|allowlist)$",
        title="Direct messages",
        description="Off ignores DMs, Open accepts DMs from anyone, Allowlist restricts to Allowed users.",
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
    setup_hint = (
        "Credential\n"
        "• Bot token: In Developer Portal → Applications → your app → Bot, reset/copy the Token. Do not use the "
        "Application ID, public key, client secret, or an OAuth invite URL.\n\n"
        "Developer Portal setup\n"
        "• Under Bot → Privileged Gateway Intents, enable Message Content Intent. This integration requests the "
        "GUILDS, GUILD_MESSAGES, DIRECT_MESSAGES, and MESSAGE_CONTENT intents.\n"
        "• Under OAuth2 → URL Generator, select the bot scope and invite the bot to each server. Grant View Channels, "
        "Send Messages, and Read Message History; grant Send Messages in Threads when using threads.\n\n"
        "Connection settings\n"
        "• The bot must be a member of every allowed server and able to view each allowed channel. Guild, channel, "
        "user, and role allowlists use Discord IDs (snowflakes); enable Developer Mode to copy them.\n"
        "• Direct messages default to Off; set Direct messages to Open or Allowlist when DMs are needed.\n"
        "• When Require @mention is enabled, mention the bot in server messages."
    )
    capabilities = frozenset(
        {
            PlatformCapability.ATTACHMENTS,
            PlatformCapability.MENTIONS,
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

    def fingerprint_material(self, credentials: PlatformCredentials) -> str:
        assert isinstance(credentials, DiscordCredentials)
        return credentials.bot_token

    def send(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelope: OutboundCommunicationEnvelope,
    ) -> str:
        assert isinstance(credentials, DiscordCredentials)
        return DiscordClient(credentials.bot_token).send_message(
            envelope.location.id,
            envelope.text,
            reply_to_id=envelope.reply_to_provider_message_id,
        )

    def normalize_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> InboundAdmissionResult:
        assert isinstance(settings, DiscordSettings)
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
            if settings.dm_policy == "off":
                return InboundAdmissionResult(CommunicationPolicyDisposition.USER_DENIED)
            if settings.dm_policy == "allowlist" and sender_id not in settings.allowed_user_ids:
                return InboundAdmissionResult(CommunicationPolicyDisposition.USER_DENIED)
        else:
            if settings.group_policy == "allowlist" and guild_id not in settings.guild_ids:
                return InboundAdmissionResult(CommunicationPolicyDisposition.CHANNEL_DENIED)
            if settings.allowed_channel_ids and channel_id not in settings.allowed_channel_ids:
                return InboundAdmissionResult(CommunicationPolicyDisposition.CHANNEL_DENIED)
            raw_member = event.get("member")
            if raw_member is not None and not isinstance(raw_member, dict):
                return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
            member_for_policy: dict[str, Any] = raw_member if isinstance(raw_member, dict) else {}
            roles = member_for_policy.get("roles", [])
            if not isinstance(roles, list):
                return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
            if (
                (settings.allowed_user_ids or settings.allowed_role_ids)
                and sender_id not in settings.allowed_user_ids
                and not set(map(str, roles)) & set(settings.allowed_role_ids)
            ):
                return InboundAdmissionResult(CommunicationPolicyDisposition.USER_DENIED)
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
            detail = " ".join(str(exc).split())[:160]
            logger.warning(
                "Discord inbound enrichment %s failed for message %s (%s): %s",
                action,
                envelope.provider_message_id,
                type(exc).__name__,
                detail,
            )
            return None

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
                if message.get("t") == "MESSAGE_CREATE" and bot_user_id:
                    message["agentbarn_bot_user_id"] = bot_user_id
                    await emit(message)
