import json
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
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
)
from api.infrastructure.slack.client import SlackClient


class SlackValidationConfig(Protocol):
    skip_slack_token_validation: bool


class SlackSettings(PlatformSettings):
    channel_ids: list[str] = Field(default_factory=list)
    dm_user_ids: list[str] = Field(default_factory=list)
    group_policy: str = Field(default="allowlist", pattern="^(open|allowlist)$")
    dm_policy: str = Field(default="off", pattern="^(off|open|allowlist)$")
    verbose_mode: bool = True


class SlackCredentials(PlatformCredentials):
    bot_token: str = Field(min_length=1)
    app_token: str = Field(min_length=1)


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
        if not isinstance(event, dict) or event.get("type") != "message" or event.get("bot_id"):
            return []
        channel_id = str(event.get("channel") or "")
        sender_id = str(event.get("user") or "")
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
        occurred_at = datetime.fromtimestamp(float(event.get("ts", "0")), tz=UTC)
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
                text=str(event.get("text") or ""),
                provider_metadata={
                    "team_id": str(payload.get("team_id") or ""),
                    "event_id": str(payload.get("event_id") or ""),
                },
            )
        ]

    async def run_ingress(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        emit: Callable[[dict[str, Any]], Awaitable[None]],
        connected: Callable[[], Awaitable[None]],
    ) -> None:
        assert isinstance(credentials, SlackCredentials)
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
                    await emit(payload)
                    await socket.send(json.dumps({"envelope_id": envelope_id}))
