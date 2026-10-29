from typing import Protocol

from pydantic import Field

from api.domains.communications.models import (
    CredentialUniquenessScope,
    PlatformCapability,
)
from api.domains.communications.plugins.base import (
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
)
from api.infrastructure.discord.client import DiscordClient

_INSTALL_OAUTH_SCOPES = "bot%20applications.commands"
_INSTALL_PERMISSIONS = 274878286912


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
