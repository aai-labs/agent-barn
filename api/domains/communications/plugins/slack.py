import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from pydantic import Field
from websockets.asyncio.client import connect

from api.domains.communications.models import (
    CommunicationSender,
    ConversationLocation,
    CredentialUniquenessScope,
    NormalizedCommunicationEnvelope,
    OutboundCommunicationEnvelope,
    PlatformCapability,
)
from api.domains.communications.plugins.base import (
    InboundAdmissionContext,
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
)
from api.infrastructure.slack.client import SlackClient


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
        min_length=1, title="Bot token", description="Starts with xoxb- — from OAuth & Permissions in your Slack app."
    )
    app_token: str = Field(
        min_length=1, title="App-level token", description="Starts with xapp- — required for Socket Mode."
    )


class SlackPlatformPlugin(PlatformPlugin):
    key = "slack"
    display_name = "Slack"
    capabilities = frozenset(
        {
            PlatformCapability.APPLICATION_PROVISIONING,
            PlatformCapability.ATTACHMENTS,
            PlatformCapability.DIRECTORY_DISCOVERY,
            PlatformCapability.MENTIONS,
            PlatformCapability.THREADS,
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
    ) -> str:
        assert isinstance(credentials, SlackCredentials)
        return SlackClient(credentials.bot_token).send_message(
            envelope.location.id,
            envelope.text,
            thread_id=envelope.location.thread_id,
        )

    def normalize_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
    ) -> list[NormalizedCommunicationEnvelope]:
        assert isinstance(settings, SlackSettings)
        event = payload.get("event")
        # Slack emits both app_mention and message events for a mentioned
        # channel message when both subscriptions are enabled. We consume the
        # message event only; accepting app_mention here would create a second
        # delivery for the same provider timestamp before persistence dedupes it.
        if (
            not isinstance(event, dict)
            or event.get("type") != "message"
            or event.get("subtype")
            or event.get("bot_id")
            or event.get("is_bot")
        ):
            return []
        channel_id = str(event.get("channel") or "")
        sender_id = str(event.get("user") or "")
        bot_user_id = self._bot_user_id(payload)
        if not sender_id or (bot_user_id and sender_id == bot_user_id):
            return []
        is_dm = event.get("channel_type") == "im"
        if is_dm:
            if settings.dm_policy == "off":
                return []
            if settings.dm_policy == "allowlist" and sender_id not in settings.dm_user_ids:
                return []
        elif settings.group_policy == "allowlist" and channel_id not in settings.channel_ids:
            return []
        message_id = str(event.get("client_msg_id") or event.get("ts") or "")
        if not channel_id or not message_id:
            return []
        try:
            occurred_at = datetime.fromtimestamp(float(event.get("ts", "0")), tz=UTC)
        except TypeError, ValueError, OSError:
            return []
        text = str(event.get("text") or "")
        return [
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
                },
            )
        ]

    def admit_inbound(
        self,
        settings: PlatformSettings,
        payload: dict[str, Any],
        *,
        context: InboundAdmissionContext,
    ) -> list[NormalizedCommunicationEnvelope]:
        assert isinstance(settings, SlackSettings)
        envelopes = self.normalize_inbound(settings, payload)
        if not envelopes:
            return []

        event = payload.get("event")
        if not isinstance(event, dict):
            return []
        is_thread_reply = bool(str(event.get("thread_ts") or ""))
        bot_user_id = self._bot_user_id(payload)
        if not bot_user_id:
            # Channel admission fails closed if ingress did not capture the
            # bot identity. DMs remain governed by dm_policy and do not need a
            # mention, but accepting an unknown channel mention is unsafe.
            return [envelope for envelope in envelopes if envelope.location.type == "DM"]

        admitted: list[NormalizedCommunicationEnvelope] = []
        for envelope in envelopes:
            if envelope.location.type == "DM" or bot_user_id in envelope.mentions:
                admitted.append(envelope)
                continue
            if (
                is_thread_reply
                and settings.thread_mention_policy == "start_only"
                and context.thread_is_agent_owned(envelope.location)
            ):
                admitted.append(envelope)
        return admitted

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
