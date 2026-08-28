import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
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
    ProcessingFeedbackStage,
)
from api.domains.communications.plugins.base import (
    InboundAdmissionContext,
    InboundAdmissionResult,
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
    ProcessingFeedbackContext,
    provider_idempotency_key,
)
from api.infrastructure.slack.client import SlackClient

logger = logging.getLogger(__name__)


class SlackValidationConfig(Protocol):
    skip_slack_token_validation: bool


class SlackSettings(PlatformSettings):
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
    thread_mention_policy: str = Field(
        default="every_message",
        pattern="^(every_message|start_only)$",
        title="Thread mention policy",
        description=(
            "Every message requires an @mention in every channel message, including thread replies. "
            "Start only requires an @mention to start a thread and then accepts unmentioned replies only in "
            "threads already owned by this Agent."
        ),
    )
    verbose_mode: bool = Field(
        default=True,
        title="Announce steps",
        description="Post a running commentary of what it's doing, not just the final reply.",
    )


class SlackCredentials(PlatformCredentials):
    bot_token: str = Field(
        min_length=1,
        title="Bot token",
        description=(
            "Starts with xoxb-. Copy it from OAuth & Permissions → OAuth Tokens for Your Workspace after installing "
            "the Slack app. Reinstall the app after changing Bot Token Scopes."
        ),
    )
    app_token: str = Field(
        min_length=1,
        title="App-level token",
        description=(
            "Starts with xapp-. Create it in Basic Information → App-Level Tokens with connections:write, then "
            "enable Socket Mode."
        ),
    )


class SlackPlatformPlugin(PlatformPlugin):
    key = "slack"
    display_name = "Slack"
    setup_hint = (
        "Credentials\n"
        "• Bot token: In OAuth & Permissions → OAuth Tokens for Your Workspace, install/reinstall the app and copy "
        "the xoxb- token.\n"
        "• App-level token: In Basic Information → App-Level Tokens, create an xapp- token with connections:write "
        "and enable Socket Mode.\n\n"
        "Bot Token Scopes\n"
        "• Messaging: chat:write, channels:history, groups:history, im:history, and mpim:history.\n"
        "• Name resolution: channels:read, groups:read, im:read, mpim:read, and users:read.\n"
        "• Processing feedback is optional but uses reactions:write.\n\n"
        "Workspace setup\n"
        "• Subscribe to message.channels, message.groups, message.im, and message.mpim events; the shipped Slack "
        "manifest includes them.\n"
        "• Invite the bot to every private channel or conversation it should handle; allowlists use channel IDs, "
        "not channel names.\n"
        "• After changing scopes, reinstall the app and replace the stored bot token."
    )
    capabilities = frozenset(
        {
            PlatformCapability.ATTACHMENTS,
            PlatformCapability.DIRECTORY_DISCOVERY,
            PlatformCapability.MENTIONS,
            PlatformCapability.THREADS,
            PlatformCapability.PROCESSING_FEEDBACK,
        }
    )
    settings_model = SlackSettings
    credentials_model = SlackCredentials
    credential_uniqueness_scope = CredentialUniquenessScope.GLOBAL

    _MENTION_PATTERN = re.compile(r"<@([^>|\s]+)(?:\|[^>]*)?>")

    def __init__(self, config: SlackValidationConfig) -> None:
        self._skip_validation = config.skip_slack_token_validation

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        assert isinstance(credentials, SlackCredentials)
        if self._skip_validation:
            return "validation-skipped"
        client = SlackClient(credentials.bot_token, credentials.app_token)
        bot_ok, bot_reason = client.validate_bot_token()
        if not bot_ok:
            raise ValueError(bot_reason)
        app_ok, app_reason = client.validate_app_token()
        if not app_ok:
            raise ValueError(app_reason)
        info = client.get_bot_info()
        team = info.get("team", "")
        username = info.get("username", "")
        return " / ".join(part for part in (team, f"@{username}" if username else "") if part) or None

    def fingerprint_material(self, credentials: PlatformCredentials) -> str:
        assert isinstance(credentials, SlackCredentials)
        return credentials.bot_token

    def send(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelope: OutboundCommunicationEnvelope,
        *,
        idempotency_key: str,
    ) -> str:
        assert isinstance(credentials, SlackCredentials)
        return SlackClient(credentials.bot_token).send_message(
            envelope.location.id,
            envelope.text,
            thread_id=envelope.location.thread_id,
            idempotency_key=provider_idempotency_key(idempotency_key),
        )

    def processing_feedback(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        context: ProcessingFeedbackContext,
    ) -> None:
        del settings
        assert isinstance(credentials, SlackCredentials)
        client = SlackClient(credentials.bot_token)

        if context.stage == ProcessingFeedbackStage.ACCEPTED:
            self._best_effort_feedback(
                "add acknowledgement reaction",
                context,
                lambda: client.add_reaction(context.location.id, context.provider_message_id or "", "eyes"),
            )
            return

        if context.stage == ProcessingFeedbackStage.CLAIMED:
            if context.location.thread_id:
                self._best_effort_feedback(
                    "set processing status",
                    context,
                    lambda: client.set_thread_status(
                        context.location.id,
                        context.location.thread_id or "",
                        "is thinking...",
                    ),
                )
            return

        self._best_effort_feedback(
            "clear processing status",
            context,
            lambda: (
                client.clear_thread_status(
                    context.location.id,
                    context.location.thread_id or "",
                )
                if context.location.thread_id
                else None
            ),
        )
        self._best_effort_feedback(
            "remove acknowledgement reaction",
            context,
            lambda: client.remove_reaction(context.location.id, context.provider_message_id or "", "eyes"),
        )
        self._best_effort_feedback(
            "add terminal reaction",
            context,
            lambda: client.add_reaction(
                context.location.id,
                context.provider_message_id or "",
                "white_check_mark" if context.stage == ProcessingFeedbackStage.SUCCEEDED else "x",
            ),
        )

    @staticmethod
    def _best_effort_feedback(
        action: str,
        context: ProcessingFeedbackContext,
        callback: Callable[[], None],
    ) -> None:
        if not context.provider_message_id and action in {
            "add acknowledgement reaction",
            "remove acknowledgement reaction",
            "add terminal reaction",
        }:
            return
        try:
            callback()
        except Exception as exc:
            logger.warning(
                "Slack processing feedback %s failed for channel %s thread %s (%s)",
                action,
                context.location.id,
                context.location.thread_id or "root",
                type(exc).__name__,
            )

    def normalize_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> InboundAdmissionResult:
        assert isinstance(settings, SlackSettings)
        event = payload.get("event")
        # Slack emits both app_mention and message events for a mentioned
        # channel message when both subscriptions are enabled. We consume the
        # message event only; accepting app_mention here would create a second
        # delivery for the same provider timestamp before persistence dedupes it.
        if not isinstance(event, dict):
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        if event.get("bot_id") or event.get("is_bot"):
            return InboundAdmissionResult(CommunicationPolicyDisposition.BOT_IGNORED)
        # Slack emits both app_mention and message events for a mentioned
        # channel message. We consume the message event only; accepting
        # app_mention here would create a second delivery for the same event.
        if event.get("type") != "message" or event.get("subtype"):
            return InboundAdmissionResult(CommunicationPolicyDisposition.BOT_IGNORED)
        channel_id = str(event.get("channel") or "")
        sender_id = str(event.get("user") or "")
        bot_user_id = self._bot_user_id(payload)
        if not sender_id:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        if bot_user_id and sender_id == bot_user_id:
            return InboundAdmissionResult(CommunicationPolicyDisposition.BOT_IGNORED)
        is_dm = event.get("channel_type") == "im"
        if is_dm:
            if settings.dm_policy == "off":
                return InboundAdmissionResult(CommunicationPolicyDisposition.USER_DENIED)
            if settings.dm_policy == "allowlist" and sender_id not in settings.dm_user_ids:
                return InboundAdmissionResult(CommunicationPolicyDisposition.USER_DENIED)
        elif settings.group_policy == "allowlist" and channel_id not in settings.channel_ids:
            return InboundAdmissionResult(CommunicationPolicyDisposition.CHANNEL_DENIED)
        # Slack reactions address messages by their provider timestamp. Keep
        # that timestamp as the canonical message identity so lifecycle
        # feedback can reliably target the inbound message; the optional
        # client-generated id remains useful metadata but is not a Slack API
        # message reference.
        message_id = str(event.get("ts") or "")
        if not channel_id or not message_id:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        try:
            occurred_at = datetime.fromtimestamp(float(event.get("ts", "0")), tz=UTC)
        except (TypeError, ValueError, OSError) as _:
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        text = str(event.get("text") or "")
        return InboundAdmissionResult(
            CommunicationPolicyDisposition.ACCEPTED,
            (
                NormalizedCommunicationEnvelope(
                    provider_message_id=message_id,
                    occurred_at=occurred_at,
                    location=ConversationLocation(
                        id=channel_id,
                        type="DM" if is_dm else "CHANNEL",
                        thread_id=str(event.get("thread_ts") or event.get("ts") or "") or None,
                    ),
                    sender=CommunicationSender(id=sender_id or None),
                    text=text,
                    mentions=self._mentioned_user_ids(text),
                    provider_metadata={
                        "team_id": str(payload.get("team_id") or ""),
                        "event_id": str(payload.get("event_id") or ""),
                        "client_msg_id": str(event.get("client_msg_id") or ""),
                    },
                ),
            ),
        )

    def admit_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
        *,
        context: InboundAdmissionContext,
    ) -> InboundAdmissionResult:
        assert isinstance(settings, SlackSettings)
        result = self.normalize_inbound(settings, payload)
        if result.disposition != CommunicationPolicyDisposition.ACCEPTED or not result.envelopes:
            return result

        event = payload.get("event")
        if not isinstance(event, dict):
            return InboundAdmissionResult(CommunicationPolicyDisposition.MALFORMED_PAYLOAD)
        is_thread_reply = bool(str(event.get("thread_ts") or ""))
        bot_user_id = self._bot_user_id(payload)
        if not bot_user_id:
            # Channel admission fails closed if ingress did not capture the
            # bot identity. DMs remain governed by dm_policy and do not need a
            # mention, but accepting an unknown channel mention is unsafe.
            if all(envelope.location.type == "DM" for envelope in result.envelopes):
                return result
            return InboundAdmissionResult(CommunicationPolicyDisposition.MENTION_REQUIRED)

        admitted: list[NormalizedCommunicationEnvelope] = []
        for envelope in result.envelopes:
            if envelope.location.type == "DM" or bot_user_id in envelope.mentions:
                admitted.append(envelope)
                continue
            if (
                is_thread_reply
                and settings.thread_mention_policy == "start_only"
                and context.thread_is_agent_owned(envelope.location)
            ):
                admitted.append(envelope)
        if admitted:
            return InboundAdmissionResult(CommunicationPolicyDisposition.ACCEPTED, tuple(admitted))
        return InboundAdmissionResult(CommunicationPolicyDisposition.MENTION_REQUIRED)

    @classmethod
    def _mentioned_user_ids(cls, text: str) -> list[str]:
        return list(dict.fromkeys(cls._MENTION_PATTERN.findall(text)))

    @staticmethod
    def _bot_user_id(payload: dict[str, Any]) -> str:
        direct = str(payload.get("agentbarn_bot_user_id") or "")
        if direct:
            return direct
        authorizations = payload.get("authorizations")
        if not isinstance(authorizations, list):
            return ""
        for authorization in authorizations:
            if not isinstance(authorization, dict):
                continue
            user_id = str(authorization.get("user_id") or "")
            if user_id and authorization.get("is_bot", True):
                return user_id
        return ""

    def enrich_inbound(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        envelopes: list[NormalizedCommunicationEnvelope],
    ) -> list[NormalizedCommunicationEnvelope]:
        del settings
        assert isinstance(credentials, SlackCredentials)
        client = SlackClient(credentials.bot_token)
        return [self._enrich_envelope(client, envelope) for envelope in envelopes]

    def _enrich_envelope(
        self,
        client: SlackClient,
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
            lookup = (
                (lambda: client.get_dm_participant_name(location.id))
                if location.type == "DM"
                else (lambda: client.get_channel_name(location.id))
            )
            name = self._safe_lookup("resolve location name", envelope, lookup)
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
                "Slack inbound enrichment %s failed for message %s (%s)",
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
        assert isinstance(credentials, SlackCredentials)
        bot_info = await asyncio.to_thread(SlackClient(credentials.bot_token).get_bot_info)
        bot_user_id = str(bot_info.get("user_id") or "")
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                "https://slack.com/api/apps.connections.open",
                headers={"Authorization": f"Bearer {credentials.app_token}"},
            )
            response.raise_for_status()
            opened = response.json()
        if not opened.get("ok") or not opened.get("url"):
            raise RuntimeError(f"Slack Socket Mode connection failed: {opened.get('error', 'unknown error')}")

        async with connect(str(opened["url"]), open_timeout=15, ping_interval=20, ping_timeout=20) as socket:
            await connected()
            async for raw in socket:
                message = json.loads(raw)
                envelope_id = message.get("envelope_id")
                payload = message.get("payload")
                if envelope_id and isinstance(payload, dict):
                    if bot_user_id:
                        payload = {**payload, "agentbarn_bot_user_id": bot_user_id}
                    await emit(payload)
                    await socket.send(json.dumps({"envelope_id": envelope_id}))
