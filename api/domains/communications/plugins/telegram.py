from typing import Protocol

from pydantic import Field, model_validator

from api.domains.communications.models import (
    CredentialUniquenessScope,
    PlatformCapability,
)
from api.domains.communications.plugins.base import (
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
)
from api.infrastructure.telegram.client import validate_bot_token


class TelegramValidationConfig(Protocol):
    skip_telegram_token_validation: bool
    agentbarn_telegram_bot_token: str


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
    home_channel_id: str | None = Field(
        default=None,
        title="Home chat",
        description=(
            "Optional group or user chat ID that scheduled results without an originating chat are sent to "
            "when the Agent runs Telegram natively."
        ),
    )
    listen_in_chat_ids: list[str] = Field(
        default_factory=list,
        title="Listen-in groups",
        description=(
            "Group IDs where the Agent reads every message without an @mention and posts only when it has "
            "something useful to add, such as a correction or missing context. Each message there costs one model "
            "turn, even when the Agent stays silent. The bot must see every group message: disable privacy mode "
            "or make it an administrator. Under Allowlist, these must also be Allowed groups. "
            "OpenClaw only for now; Hermes Agents still answer only when mentioned."
        ),
    )

    @model_validator(mode="after")
    def require_allowed_listen_in_groups(self) -> TelegramSettings:
        if self.group_policy == "allowlist" and (outside := set(self.listen_in_chat_ids) - set(self.allowed_chat_ids)):
            raise ValueError(f"Listen-in groups must also be Allowed groups: {', '.join(sorted(outside))}")
        return self


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
        "2. Add the bot to every group it should handle. Make it a group administrator, or use "
        "[@BotFather](https://t.me/BotFather) → `/setprivacy` → **Disable**, then remove and re-add the bot "
        "to the group. Privacy mode can prevent ordinary @mentions from reaching the bot. The native runtime "
        "still answers groups only when mentioned or replied to, subject to Connection access. Listen-in groups "
        "need the bot to see every message, so disable privacy mode or make the bot an administrator there. "
        "See [Telegram privacy mode](https://core.telegram.org/bots/features#privacy-mode).\n"
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
        self._shared_bot_token = config.agentbarn_telegram_bot_token

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        assert isinstance(credentials, TelegramCredentials)
        # Telegram allows one consumer per bot, so a Connection on the deployment's shared
        # bot would compete with Agent Barn Telegram for its updates. The bot id is the
        # token's prefix and survives a token revoke, so it is what is compared.
        shared_bot_id = self._shared_bot_token.strip().split(":", 1)[0]
        if shared_bot_id and credentials.bot_token.strip().split(":", 1)[0] == shared_bot_id:
            raise ValueError(
                "This is Agent Barn's own Telegram bot. Create a bot of your own with @BotFather, "
                "or use Agent Barn Telegram instead."
            )
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
