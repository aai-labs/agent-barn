import logging
import math
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from injector import inject, singleton

from api.core.config import Config
from api.domains.communications.agentbarn_telegram_rate_limit import TelegramRateLimiter
from api.domains.communications.agentbarn_telegram_repository import AgentBarnTelegramRepository
from api.domains.communications.plugins.agentbarn_telegram import runtime_api_token
from api.infrastructure.crypto import decrypt_token

logger = logging.getLogger(__name__)

_TELEGRAM = "https://api.telegram.org"
_TIMEOUT_SECONDS = 60
_CHAT_ID = re.compile(r"^-?\d+$")
_BLOCKED_BY_USER = "bot was blocked by the user"
# Telegram file paths look like "photos/file_7.jpg"; nothing that could climb out
# of the file area into the Bot API, which the real token would also unlock.
_FILE_PATH = re.compile(r"^[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+(?:\.[A-Za-z0-9]+)?)*$")

# Startup and housekeeping calls that would change the bot for every
# Organization. Each runtime makes some of these when it starts; they are
# answered as successes and never reach Telegram.
_ANSWERED_AS_DONE = frozenset(
    {
        "setwebhook",
        "deletewebhook",
        "setmycommands",
        "deletemycommands",
        "setmydescription",
        "setmyshortdescription",
        "setmyname",
        "setchatmenubutton",
        "setmydefaultadministratorrights",
        "logout",
        "close",
    }
)
# Calls that act on a chat; every chat they name must be a user linked to the caller.
_CHAT_SCOPED = frozenset(
    {
        "sendmessage",
        "sendphoto",
        "senddocument",
        "sendaudio",
        "sendvoice",
        "sendvideo",
        "sendvideonote",
        "sendanimation",
        "sendsticker",
        "sendmediagroup",
        "sendlocation",
        "sendvenue",
        "sendcontact",
        "sendpoll",
        "senddice",
        "sendchataction",
        "editmessagetext",
        "editmessagecaption",
        "editmessagemedia",
        "editmessagereplymarkup",
        "editmessagelivelocation",
        "stopmessagelivelocation",
        "stoppoll",
        "deletemessage",
        "deletemessages",
        "setmessagereaction",
        "copymessage",
        "copymessages",
        "forwardmessage",
        "forwardmessages",
        "pinchatmessage",
        "unpinchatmessage",
    }
)
# Calls addressed by an id Telegram issued for the caller's own conversation.
_UNSCOPED = frozenset({"answercallbackquery", "getfile"})
_CHAT_FIELDS = ("chat_id", "from_chat_id")


@dataclass(frozen=True)
class ProxyResponse:
    status_code: int
    body: dict[str, Any]


@dataclass(frozen=True)
class ProxyFile:
    status_code: int
    content: bytes
    content_type: str | None


def _error(code: int, description: str) -> ProxyResponse:
    return ProxyResponse(code, {"ok": False, "error_code": code, "description": description})


@inject
@singleton
@dataclass
class AgentBarnTelegramProxy:
    """The Telegram Bot API as an Agent on Agent Barn Telegram sees it.

    The Agent's runtime is pointed here with a stand-in token. Only calls that
    serve that Agent's own linked users reach Telegram, carrying the real token;
    calls that would change the shared bot are answered here, and everything
    else is refused.
    """

    config: Config
    repository: AgentBarnTelegramRepository
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=_TIMEOUT_SECONDS), init=False)
    _bot: dict[str, Any] | None = field(default=None, init=False)
    _limiter: TelegramRateLimiter = field(init=False)

    def __post_init__(self) -> None:
        self._limiter = TelegramRateLimiter(
            bot_per_second=self.config.agentbarn_telegram_bot_rate_per_second,
            organization_per_second=self.config.agentbarn_telegram_organization_rate_per_second,
        )

    def handle(
        self,
        connection_id: UUID,
        token: str,
        method: str,
        *,
        params: dict[str, Any],
        body: bytes,
        content_type: str | None,
    ) -> ProxyResponse:
        authenticated = self._authenticate(connection_id, token)
        if authenticated is None:
            return _error(401, "Unauthorized")
        real_token, organization_id = authenticated

        name = method.lower()
        if name == "getme":
            return self._get_me(real_token)
        if name == "getwebhookinfo":
            return ProxyResponse(
                200, {"ok": True, "result": {"url": "", "has_custom_certificate": False, "pending_update_count": 0}}
            )
        if name == "getmycommands":
            return ProxyResponse(200, {"ok": True, "result": []})
        if name in _ANSWERED_AS_DONE:
            return ProxyResponse(200, {"ok": True, "result": True})
        if name in _CHAT_SCOPED:
            chats = self._named_chats(params)
            if not chats or not chats <= self.repository.linked_user_ids(connection_id):
                return _error(403, "Forbidden: this chat is not linked to this agent")
            wait = self._limiter.acquire(organization_id, now=time.monotonic())
            if wait > 0:
                if name == "sendchataction":
                    # A typing indicator is a courtesy; skipping one beats delaying the reply.
                    return ProxyResponse(200, {"ok": True, "result": True})
                retry_after = max(1, math.ceil(wait))
                return ProxyResponse(
                    429,
                    {
                        "ok": False,
                        "error_code": 429,
                        "description": f"Too Many Requests: retry after {retry_after}",
                        "parameters": {"retry_after": retry_after},
                    },
                )
        elif name not in _UNSCOPED:
            return _error(403, "Forbidden: this method is not available")

        response = self._forward(real_token, method, body, content_type)
        if (
            name in _CHAT_SCOPED
            and response.status_code == 403
            and _BLOCKED_BY_USER in str(response.body.get("description", ""))
        ):
            for chat in self._named_chats(params) or set():
                self.repository.end_link_for_connection(connection_id, chat, now=datetime.now(UTC))
        return response

    def download(self, connection_id: UUID, token: str, file_path: str) -> ProxyFile:
        """A file a linked user sent, from Telegram's file area, fetched with the real token."""
        authenticated = self._authenticate(connection_id, token)
        if authenticated is None:
            return ProxyFile(401, b"", None)
        real_token, _ = authenticated
        if not _FILE_PATH.match(file_path):
            return ProxyFile(404, b"", None)
        try:
            response = self.client.get(f"{_TELEGRAM}/file/bot{real_token}/{file_path}")
        except httpx.HTTPError as exc:
            logger.warning("Agent Barn Telegram proxy could not reach Telegram (%s)", type(exc).__name__)
            return ProxyFile(502, b"", None)
        if not response.is_success:
            return ProxyFile(response.status_code, b"", None)
        return ProxyFile(200, response.content, response.headers.get("Content-Type"))

    def _authenticate(self, connection_id: UUID, token: str) -> tuple[str, UUID] | None:
        """The real bot token and caller's Organization when ``token`` is this Connection's stand-in."""
        connection = self.repository.proxy_connection(connection_id)
        real_token = self.config.agentbarn_telegram_bot_token.strip()
        if connection is None or not real_token:
            return None
        driver_key = decrypt_token(connection.driver_key_encrypted, self.config.agent_token_encryption_key)
        if not secrets.compare_digest(token, runtime_api_token(driver_key, real_token)):
            return None
        return real_token, connection.organization_id

    @staticmethod
    def _named_chats(params: dict[str, Any]) -> set[int] | None:
        """The chats a call names, or None when one is not a private chat id."""
        chats: set[int] = set()
        for name in _CHAT_FIELDS:
            if name not in params:
                continue
            value = str(params[name])
            if not _CHAT_ID.match(value):
                return None
            chats.add(int(value))
        return chats

    def _get_me(self, real_token: str) -> ProxyResponse:
        if self._bot is None:
            response = self._forward(real_token, "getMe", b"", None)
            if response.status_code != 200 or not response.body.get("ok"):
                return response
            self._bot = response.body
        return ProxyResponse(200, self._bot)

    def _forward(self, real_token: str, method: str, body: bytes, content_type: str | None) -> ProxyResponse:
        headers = {"Content-Type": content_type} if content_type else {}
        try:
            response = self.client.post(f"{_TELEGRAM}/bot{real_token}/{method}", content=body, headers=headers)
        except httpx.HTTPError as exc:
            # httpx errors carry the URL, and with it the real token.
            logger.warning("Agent Barn Telegram proxy could not reach Telegram (%s)", type(exc).__name__)
            return _error(502, "Bad Gateway: Telegram is unreachable")
        try:
            payload = response.json()
        except ValueError:
            return _error(502, "Bad Gateway: unexpected answer from Telegram")
        return ProxyResponse(response.status_code, payload if isinstance(payload, dict) else {"ok": False})
