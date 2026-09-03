import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
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
from api.infrastructure.telegram.client import get_chat_display_name, send_message, validate_bot_token

logger = logging.getLogger(__name__)


class TelegramValidationConfig(Protocol):
    skip_telegram_token_validation: bool


class TelegramSettings(PlatformSettings):
    allowed_user_ids: list[str] = Field(
        default_factory=list,
        title="Allowed DM senders",
        description="User IDs allowed to direct-message this agent. Used when Direct messages is Allowlist.",
    )
    allowed_chat_ids: list[str] = Field(
        default_factory=list,
        title="Allowed groups",
        description="Group/chat IDs this agent may respond in. Used when Group access is Allowlist.",
    )
    group_policy: str = Field(
        default="allowlist",
        pattern="^(open|allowlist)$",
        title="Group access",
        description="Open responds in any group it's added to. Allowlist restricts it to Allowed groups.",
    )
    dm_policy: str = Field(
        default="off",
        pattern="^(off|open|allowlist)$",
        title="Direct messages",
        description="Off ignores DMs, Open accepts DMs from anyone, Allowlist restricts to Allowed DM senders.",
    )


class TelegramCredentials(PlatformCredentials):
    bot_token: str = Field(
        min_length=1,
        title="Bot token",
        description=(
            "Create a bot with @BotFather using /newbot and paste the token it returns, usually formatted as "
            "<bot-id>:<secret>. Do not paste the bot username."
        ),
    )


class TelegramPlatformPlugin(PlatformPlugin):
    key = "telegram"
    display_name = "Telegram"
    setup_hint = (
        "## Create a bot\n\n"
        "1. Open [@BotFather](https://t.me/BotFather), run `/newbot`, and copy the token in the `<bot-id>:<secret>` "
        "format. Keep it private; Telegram has no separate app token or OAuth credential for this Connection.\n\n"
        "## Configure Telegram\n\n"
        "1. This integration uses `getUpdates` long polling. Remove any existing webhook and stop other services polling "
        "the same bot token before connecting.\n"
        "2. Add the bot to every group or channel it should handle. For ordinary group messages, use **@BotFather → "
        "/setprivacy → Disable**; privacy mode otherwise delivers mainly commands, replies, and mentions.\n"
        "3. For channels, make the bot an administrator so it can receive channel posts and send replies.\n\n"
        "## Set Connection access\n\n"
        "1. Direct messages default to Off; set Direct messages to Open or Allowlist when DMs are needed.\n"
        "2. Allowed groups and Allowed DM senders use numeric Telegram IDs, not usernames; group and supergroup IDs are "
        "often negative."
    )
    capabilities = frozenset(
        {
            PlatformCapability.ATTACHMENTS,
            PlatformCapability.MENTIONS,
            PlatformCapability.THREADS,
        }
    )
    settings_model = TelegramSettings
    credentials_model = TelegramCredentials
    credential_uniqueness_scope = CredentialUniquenessScope.GLOBAL

    def __init__(self, config: TelegramValidationConfig) -> None:
        self._skip_validation = config.skip_telegram_token_validation

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        assert isinstance(credentials, TelegramCredentials)
        if self._skip_validation:
            return "validation-skipped"
        ok, reason, bot_info = validate_bot_token(credentials.bot_token)
        if not ok:
            raise ValueError(reason)
        username = bot_info.get("username", "")
        return f"@{username}" if username else None

    def fingerprint_material(self, credentials: PlatformCredentials) -> str:
        assert isinstance(credentials, TelegramCredentials)
        return credentials.bot_token

    def send(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelope: OutboundCommunicationEnvelope,
        *,
        idempotency_key: str,
    ) -> str:
        assert isinstance(credentials, TelegramCredentials)
        return send_message(
            credentials.bot_token,
            envelope.location.id,
            envelope.text,
            thread_id=envelope.location.thread_id,
            idempotency_key=provider_idempotency_key(idempotency_key),
        )

    def normalize_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> InboundAdmissionResult:
        assert isinstance(settings, TelegramSettings)
        message = payload.get("message") or payload.get("channel_post")
        if not isinstance(message, dict):
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        chat = message.get("chat")
        sender = message.get("from") or {}
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        if sender.get("is_bot"):
            return InboundAdmissionResult(CommunicationPolicyDisposition.BOT_IGNORED)
        chat_id = str(chat.get("id") or "")
        sender_id = str(sender.get("id") or "")
        is_dm = chat.get("type") == "private"
        if is_dm:
            if settings.dm_policy == "off":
                return InboundAdmissionResult(CommunicationPolicyDisposition.USER_DENIED)
            if settings.dm_policy == "allowlist" and sender_id not in settings.allowed_user_ids:
                return InboundAdmissionResult(CommunicationPolicyDisposition.USER_DENIED)
        elif settings.group_policy == "allowlist" and chat_id not in settings.allowed_chat_ids:
            return InboundAdmissionResult(CommunicationPolicyDisposition.CHANNEL_DENIED)
        message_id = str(message.get("message_id") or "")
        if not chat_id or not message_id:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        display_name = " ".join(
            part for part in (str(sender.get("first_name") or ""), str(sender.get("last_name") or "")) if part
        )
        raw_date = message.get("date")
        if raw_date is None:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        try:
            occurred_at = datetime.fromtimestamp(int(raw_date), tz=UTC)
            update_id = int(payload.get("update_id") or 0)
        except (TypeError, ValueError, OSError) as _:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        return InboundAdmissionResult(
            CommunicationPolicyDisposition.ACCEPTED,
            (
                NormalizedCommunicationEnvelope(
                    provider_message_id=message_id,
                    occurred_at=occurred_at,
                    location=ConversationLocation(
                        id=chat_id,
                        type="DM" if is_dm else "CHANNEL",
                        display_name=str(chat.get("title") or chat.get("username") or "") or None,
                        thread_id=str(message.get("message_thread_id") or "") or None,
                    ),
                    sender=CommunicationSender(id=sender_id or None, display_name=display_name or None),
                    text=str(message.get("text") or message.get("caption") or ""),
                    reply_to_provider_message_id=(
                        str(message.get("reply_to_message", {}).get("message_id"))
                        if isinstance(message.get("reply_to_message"), dict)
                        else None
                    ),
                    provider_metadata={"update_id": update_id},
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
        assert isinstance(credentials, TelegramCredentials)
        return [self._enrich_envelope(credentials.bot_token, envelope) for envelope in envelopes]

    def _enrich_envelope(
        self,
        bot_token: str,
        envelope: NormalizedCommunicationEnvelope,
    ) -> NormalizedCommunicationEnvelope:
        sender = envelope.sender
        if sender.id and not sender.display_name:
            name = self._safe_lookup(
                "resolve sender name",
                envelope,
                lambda: get_chat_display_name(bot_token, sender.id or ""),
            )
            if name:
                sender = sender.model_copy(update={"display_name": name})

        location = envelope.location
        if not location.display_name:
            name = self._safe_lookup(
                "resolve location name",
                envelope,
                lambda: get_chat_display_name(bot_token, location.id),
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
                "Telegram inbound enrichment %s failed for message %s (%s)",
                action,
                envelope.provider_message_id,
                type(exc).__name__,
            )
            return None

    async def run_ingress(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        emit: Callable[[dict[str, Any]], Awaitable[None]],
        connected: Callable[[], Awaitable[None]],
    ) -> None:
        assert isinstance(credentials, TelegramCredentials)
        offset: int | None = None
        await connected()
        async with httpx.AsyncClient(timeout=40) as client:
            while True:
                params: dict[str, int] = {"timeout": 30}
                if offset is not None:
                    params["offset"] = offset
                response = await client.get(
                    f"https://api.telegram.org/bot{credentials.bot_token}/getUpdates",
                    params=params,
                )
                response.raise_for_status()
                body = response.json()
                if not body.get("ok"):
                    raise RuntimeError(f"Telegram getUpdates error: {body.get('description', 'unknown error')}")
                for update in body.get("result", []):
                    if not isinstance(update, dict):
                        continue
                    await emit(update)
                    update_id = update.get("update_id")
                    if isinstance(update_id, int):
                        offset = update_id + 1
