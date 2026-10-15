import hashlib
import hmac
from dataclasses import dataclass
from typing import Protocol

from api.domains.communications.models import CommunicationPlatform, PlatformCapability
from api.domains.communications.plugins.base import (
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
)

# Where an Agent's runtime listens for the updates Agent Barn forwards. Both
# runtimes take the port and path as settings, so one value serves both.
RUNTIME_WEBHOOK_PORT = 8443
RUNTIME_WEBHOOK_PATH = "/telegram"

_RUNTIME_WEBHOOK_SECRET_CONTEXT = b"agentbarn-telegram-runtime-webhook"


def runtime_webhook_secret(connection_secret: str) -> str:
    """The secret Agent Barn presents to an Agent's Telegram webhook, from its Connection's secret.

    Each Connection's differs, and it reveals neither the Connection's secret nor
    the stand-in token. Hex output fits Telegram's secret_token alphabet.
    """
    return hmac.new(connection_secret.encode("utf-8"), _RUNTIME_WEBHOOK_SECRET_CONTEXT, hashlib.sha256).hexdigest()


_RUNTIME_API_TOKEN_CONTEXT = b"agentbarn-telegram-runtime-api"


def runtime_api_token(connection_secret: str, bot_token: str) -> str:
    """The stand-in bot token an Agent's runtime uses against Agent Barn's Telegram proxy.

    It keeps the real bot's numeric id, so it is shaped like any bot token, and
    replaces the secret half with one derived from the Connection's secret.
    The real token never reaches the Agent.
    """
    bot_id = bot_token.split(":", 1)[0]
    secret = hmac.new(connection_secret.encode("utf-8"), _RUNTIME_API_TOKEN_CONTEXT, hashlib.sha256).hexdigest()
    return f"{bot_id}:{secret}"


@dataclass(frozen=True)
class AgentBarnTelegramRuntime:
    """What an Agent's runtime needs to use Agent Barn Telegram through the proxy."""

    # The Bot API root to use instead of https://api.telegram.org.
    api_root: str
    # Stand-in bot token accepted only by the proxy, for this Connection.
    api_token: str
    # Secret the runtime's webhook requires on every forwarded update.
    webhook_secret: str
    # Where Agent Barn reaches the runtime's webhook; the runtime only registers it.
    webhook_url: str


class AgentBarnTelegramConfig(Protocol):
    agentbarn_telegram_bot_token: str
    agentbarn_telegram_bot_username: str


class AgentBarnTelegramSettings(PlatformSettings):
    pass


class AgentBarnTelegramCredentials(PlatformCredentials):
    pass


class AgentBarnTelegramPlatformPlugin(PlatformPlugin):
    """Telegram through Agent Barn's own bot, shared by every Organization.

    The user brings nothing: people link their Telegram account to an Agent and
    the bot routes their private chats to it. The Agent runtime's native Telegram
    adapter carries the traffic, so the Communications gateway never supervises
    this Platform and it declares no gateway capabilities.
    """

    key = CommunicationPlatform.AGENTBARN_TELEGRAM.value
    display_name = "Agent Barn Telegram"
    setup_hint = "Talk to this agent in Telegram without creating a bot. After adding it, link your Telegram account."
    capabilities = frozenset({PlatformCapability.ACCOUNT_LINKING})
    settings_model = AgentBarnTelegramSettings
    credentials_model = AgentBarnTelegramCredentials

    def __init__(self, config: AgentBarnTelegramConfig) -> None:
        self.config = config

    @property
    def bot_username(self) -> str:
        return self.config.agentbarn_telegram_bot_username.strip().lstrip("@")

    def is_offered(self) -> bool:
        """Offered only in environments that have Agent Barn's own bot configured."""
        return bool(self.config.agentbarn_telegram_bot_token.strip() and self.bot_username)

    def validate_external(self, settings: PlatformSettings, credentials: PlatformCredentials) -> str | None:
        del settings, credentials
        return f"@{self.bot_username}"
