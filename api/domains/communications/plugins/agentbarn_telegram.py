import hashlib
import hmac
from typing import Protocol

from api.domains.communications.models import CommunicationPlatform
from api.domains.communications.plugins.base import (
    PlatformCredentials,
    PlatformPlugin,
    PlatformSettings,
)

_RUNTIME_WEBHOOK_SECRET_CONTEXT = b"agentbarn-telegram-runtime-webhook"


def runtime_webhook_secret(driver_key: str) -> str:
    """The secret Agent Barn presents to an Agent's Telegram webhook, from its Connection's driver key.

    Both sides derive it, so it is never stored or sent on its own, and each
    Connection's differs. Hex output fits Telegram's secret_token alphabet.
    """
    return hmac.new(driver_key.encode("utf-8"), _RUNTIME_WEBHOOK_SECRET_CONTEXT, hashlib.sha256).hexdigest()


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
