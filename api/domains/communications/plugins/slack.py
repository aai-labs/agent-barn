import re
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from api.domains.communications.models import (
    ConversationLocation,
    CredentialUniquenessScope,
    OutboundTargetRequest,
    PlatformCapability,
    ResolvedOutboundTarget,
)
from api.domains.communications.plugins.base import (
    NativeHomeDeliverySettings,
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
)
from api.infrastructure.slack.client import SlackClient


class SlackValidationConfig(Protocol):
    skip_slack_token_validation: bool


class SlackSettings(NativeHomeDeliverySettings, PlatformSettings):
    @model_validator(mode="before")
    @classmethod
    def discard_legacy_verbose_mode(cls, values: object) -> object:
        """Accept old Connection rows while retiring the unused setting."""
        if isinstance(values, dict) and "verbose_mode" in values:
            return {key: value for key, value in values.items() if key != "verbose_mode"}
        return values

    channel_ids: list[str] = Field(
        default_factory=list,
        title="Allowed channels",
        description="Channel IDs this agent may read and post in. Used when Channel access is Allowlist.",
    )
    dm_user_ids: list[str] = Field(
        default_factory=list,
        title="Allowed DM users",
        description="User IDs allowed to exchange direct messages with this Agent, including native scheduled home delivery. Used when Direct messages is Allowlist.",
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
        description="Off ignores DMs, Open accepts DMs from anyone, Allowlist restricts to Allowed DM users.",
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
    listen_in_channel_ids: list[str] = Field(
        default_factory=list,
        title="Listen-in channels",
        description=(
            "Channel IDs where the Agent reads every message without an @mention and posts only when it has "
            "something useful to add, such as a correction or missing context. Each message there costs one model "
            "turn, even when the Agent stays silent. Under Allowlist, these must also be Allowed channels. "
            "On Hermes, Verbose mode is off for this platform and new messages wait for the running "
            "turn instead of interrupting it."
        ),
    )

    # Not stored when empty: a release without this setting rejects unknown keys, so a
    # plain Slack Connection saved now must stay readable after a rollback.
    api_url: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
        title="Custom Slack server",
        description=(
            "Leave empty for Slack. For a self-hosted chat that implements Slack's bot API with Socket Mode, enter "
            "its Slack API address, for example https://chat.example.com/slack/api/. Its administrator issues the "
            "bot and app-level tokens. Hermes Agents only; not available for Bots."
        ),
    )

    @field_validator("api_url", mode="before")
    @classmethod
    def normalize_api_url(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if not isinstance(value, str):
            return value
        url = value.strip()
        parts = urlsplit(url)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or parts.query:
            raise ValueError("Custom Slack server must be an https URL without credentials or a query")
        host = parts.hostname.lower().rstrip(".")
        if host == "slack.com" or host.endswith(".slack.com"):
            raise ValueError("Leave Custom Slack server empty to use Slack itself")
        return url.rstrip("/") + "/"

    @model_validator(mode="after")
    def require_allowed_listen_in_channels(self) -> SlackSettings:
        if self.group_policy == "allowlist" and (outside := set(self.listen_in_channel_ids) - set(self.channel_ids)):
            raise ValueError(f"Listen-in channels must also be Allowed channels: {', '.join(sorted(outside))}")
        return self


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


def _resolve_unique_name(entries: list[dict], recipient: str, *, fields: tuple[str, ...]) -> str:
    """Reject ambiguous names instead of guessing which match the Agent meant."""
    name = recipient.lstrip("#@").casefold()
    matches = {
        str(entry["id"])
        for entry in entries
        if any(str(entry.get(field) or "").lstrip("#@").casefold() == name for field in fields)
    }
    if len(matches) != 1:
        raise ValueError("Unknown or ambiguous target; use its provider ID")
    return matches.pop()


class SlackPlatformPlugin(PlatformPlugin):
    key = "slack"
    display_name = "Slack"
    schema_version = 2
    setup_hint = (
        "## Create a Slack app\n\n"
        "1. Open [Slack app management](https://api.slack.com/apps).\n"
        "2. Click **New App**.\n"
        "3. Click **From Manifest**.\n"
        "4. Copy and paste the provided manifest using **Copy Slack manifest** below.\n"
        "5. Select a workspace and click **Next**.\n"
        "6. Click **Create**.\n\n"
        "## Create credentials\n\n"
        "1. In **Basic Information → App-Level Tokens**, create a token with `connections:write` and copy the `xapp-` "
        "value. Slack requires this manual step; manifests cannot create app-level tokens.\n"
        "2. In **OAuth & Permissions**, install or reinstall the app in the workspace, then copy the `xoxb-` token from "
        "**OAuth Tokens for Your Workspace**. Reinstall after every scope change.\n"
        "3. Paste the `xoxb-` bot token and `xapp-` app-level token into this Connection.\n\n"
        "## Grant channel access\n\n"
        "Invite the bot to every private channel or conversation it should handle. Allowlist values are Slack IDs; use "
        "the channel and user suggestions after saving this Connection."
    )
    capabilities = frozenset(
        {
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

    def resolve_outbound_target(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        request: OutboundTargetRequest,
    ) -> ResolvedOutboundTarget:
        assert isinstance(settings, SlackSettings)
        assert isinstance(credentials, SlackCredentials)
        client = SlackClient(credentials.bot_token, api_url=settings.api_url)
        recipient = request.recipient
        if request.thread_id and not re.fullmatch(r"[0-9]+\.[0-9]{6}", request.thread_id):
            raise ValueError("Slack thread must be a message timestamp")
        user_id = None
        if request.kind == "user":
            user_id = (
                recipient
                if re.fullmatch(r"[UW][A-Z0-9]+", recipient)
                else _resolve_unique_name(
                    client.list_users(),
                    recipient,
                    fields=("name", "real_name", "display_name"),
                )
            )
            provisional = ResolvedOutboundTarget(
                location=ConversationLocation(id=user_id, type="DM"),
                provider_metadata={"outbound_user_id": user_id},
            )
            self.validate_outbound_target(settings, provisional)
            recipient = client.open_dm(user_id)
        elif not re.fullmatch(r"[CDG][A-Z0-9]+", recipient):
            recipient = _resolve_unique_name(client.list_channels(), recipient, fields=("name",))
        conversation = client.get_conversation(recipient)
        if conversation.get("is_mpim"):
            raise ValueError("Group DMs are not supported as native scheduled home targets")
        is_dm = bool(conversation.get("is_im"))
        if (request.kind in {"user", "dm"}) != is_dm:
            raise ValueError("Target kind does not match the Slack conversation")
        target = ResolvedOutboundTarget(
            location=ConversationLocation(
                id=recipient,
                type="DM" if is_dm else "CHANNEL",
                display_name=conversation.get("name"),
                thread_id=request.thread_id,
            ),
            provider_metadata={"outbound_user_id": user_id or conversation.get("user")},
        )
        self.validate_outbound_target(settings, target)
        return target

    def validate_outbound_target(self, settings: PlatformSettings, target: ResolvedOutboundTarget) -> None:
        """Reuse the inbound allowlists as outbound restrictions; DMs stay off unless DM policy allows them."""
        assert isinstance(settings, SlackSettings)
        location = target.location
        if location.type == "DM":
            user_id = str(target.provider_metadata.get("outbound_user_id") or "")
            if (
                not user_id
                or settings.dm_policy == "off"
                or (settings.dm_policy == "allowlist" and user_id not in settings.dm_user_ids)
            ):
                raise PermissionError("Outbound recipient is not allowed by this Connection")
        elif settings.group_policy == "allowlist" and location.id not in settings.channel_ids:
            raise PermissionError("Outbound channel is not allowed by this Connection")

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        assert isinstance(settings, SlackSettings)
        assert isinstance(credentials, SlackCredentials)
        if self._skip_validation:
            return "validation-skipped"
        client = SlackClient(credentials.bot_token, credentials.app_token, api_url=settings.api_url)
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

    def list_directory_entries(
        self,
        settings: PlatformSettings,
        credentials: PlatformCredentials,
        *,
        kind: str,
        search: str | None = None,
        guild_id: str | None = None,
    ) -> list[dict[str, str | None]]:
        del guild_id
        assert isinstance(settings, SlackSettings)
        assert isinstance(credentials, SlackCredentials)
        client = SlackClient(credentials.bot_token, api_url=settings.api_url)
        if kind == "channels":
            return [
                {
                    "id": channel["id"],
                    "label": f"#{channel['name']}" if channel["name"] else channel["id"],
                    "detail": "Private channel" if channel["is_private"] else None,
                }
                for channel in client.list_channels(search)
            ]
        if kind == "users":
            return [
                {
                    "id": user["id"],
                    "label": user["display_name"] or user["real_name"] or user["name"] or user["id"],
                    "detail": f"@{user['name']}" if user["name"] else None,
                }
                for user in client.list_users(search)
            ]
        raise ValueError(f"Unsupported Slack directory kind: {kind}")
