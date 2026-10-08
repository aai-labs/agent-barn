import json
import logging
import math
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import parse_qsl, urlencode
from uuid import UUID

import httpx
from injector import inject, singleton

from api.core.config import Config
from api.domains.communications.agentbarn_telegram_rate_limit import AgentBarnTelegramRateLimits
from api.domains.communications.agentbarn_telegram_repository import AgentBarnTelegramRepository
from api.domains.communications.agentbarn_telegram_service import AgentBarnTelegramService
from api.domains.communications.plugins.agentbarn_telegram import runtime_api_token

logger = logging.getLogger(__name__)

_TELEGRAM = "https://api.telegram.org"
_TIMEOUT_SECONDS = 60
_CHAT_ID = re.compile(r"-?[0-9]+")
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
# Telegram keeps a getFile download link valid for at least an hour.
_FILE_LINK_SECONDS = 3600

_JSON = "application/json"
_FORM = "application/x-www-form-urlencoded"
_MULTIPART = "multipart/form-data"


class BadBotApiRequest(ValueError):
    """A call the proxy cannot read unambiguously, so it must not be forwarded."""


@dataclass(frozen=True)
class UploadedFile:
    field: str
    filename: str
    content: bytes
    content_type: str | None


@dataclass(frozen=True)
class BotApiRequest:
    """One Bot API call exactly as the proxy read it. Only this is ever forwarded."""

    params: dict[str, Any]
    encoding: Literal["json", "form", "multipart"] = "json"
    files: tuple[UploadedFile, ...] = ()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BadBotApiRequest(f"duplicate parameter {key}")
        result[key] = value
    return result


def _strict_json(text: str | bytes) -> Any:
    try:
        return json.loads(text, object_pairs_hook=lambda pairs: _unique(list(pairs)))
    except BadBotApiRequest:
        raise
    except ValueError as exc:
        raise BadBotApiRequest("not valid JSON") from exc


# Parameters the proxy reads inside of, which runtimes may send as JSON text.
_CHECKED_JSON_TEXT = ("reply_parameters",)


def parse_bot_api_request(
    query: list[tuple[str, str]],
    content_type: str | None,
    body: bytes,
    form: list[tuple[str, str | UploadedFile]] | None = None,
) -> BotApiRequest:
    """Read a Bot API call strictly: one value per parameter, in a content type the proxy understands.

    Anything another parser could read differently (duplicate keys, a parameter
    in both the query and the body, an unknown or missing content type) is
    refused, because the proxy forwards what it read rather than the bytes it got.
    """
    params = _unique(query)
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if not body and media_type != _MULTIPART:
        return BotApiRequest(params=params)
    if media_type == _JSON:
        parsed = _strict_json(body)
        if not isinstance(parsed, dict):
            raise BadBotApiRequest("body must be a JSON object")
        body_params, encoding, files = parsed, "json", ()
    elif media_type == _FORM:
        try:
            pairs = parse_qsl(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True)
        except (UnicodeDecodeError, ValueError) as exc:
            raise BadBotApiRequest("body is not a valid form") from exc
        body_params, encoding, files = _unique(pairs), "form", ()
    elif media_type == _MULTIPART:
        fields = _unique(list(form or []))
        body_params = {key: value for key, value in fields.items() if isinstance(value, str)}
        files = tuple(value for value in fields.values() if isinstance(value, UploadedFile))
        encoding = "multipart"
    else:
        raise BadBotApiRequest("unsupported content type")
    overlap = params.keys() & body_params.keys()
    if overlap:
        raise BadBotApiRequest(f"parameter {min(overlap)} given twice")
    merged = {**params, **body_params}
    for name in _CHECKED_JSON_TEXT:
        if isinstance(merged.get(name), str):
            # Checked and forwarded as one reading, never as the text received.
            merged[name] = json.dumps(_strict_json(merged[name]))
    return BotApiRequest(params=merged, encoding=encoding, files=files)


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
    connection_secrets: AgentBarnTelegramService
    limits: AgentBarnTelegramRateLimits
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=_TIMEOUT_SECONDS), init=False)
    _bot: dict[str, Any] | None = field(default=None, init=False)
    # File paths each Connection looked up with getFile, until their links expire.
    # Every Organization shares the bot's file area, so a Connection may download
    # only files it was shown. Per process, like the rate limits.
    _files: dict[tuple[UUID, str], float] = field(default_factory=dict, init=False)
    _files_lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def handle(self, connection_id: UUID, token: str, method: str, *, request: BotApiRequest) -> ProxyResponse:
        authenticated = self._authenticate(connection_id, token)
        if authenticated is None:
            return _error(401, "Unauthorized")
        real_token, organization_id = authenticated
        params = request.params

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
        if "business_connection_id" in params:
            return _error(403, "Forbidden: business connections are not available")
        if name in _CHAT_SCOPED:
            chats = self._named_chats(params)
            if not chats or not chats <= self.repository.linked_user_ids(connection_id):
                return _error(403, "Forbidden: this chat is not linked to this agent")
            wait = self.limits.acquire_for_organization(organization_id)
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

        response = self._forward(real_token, method, request)
        if name == "getfile":
            self._remember_file(connection_id, response)
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
        if not _FILE_PATH.match(file_path) or not self._was_shown(connection_id, file_path):
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
        # An Agent that never started with this Connection has no stand-in token to present.
        connection_secret = self.connection_secrets.runtime_secret(connection.id, create=False)
        if connection_secret is None or not secrets.compare_digest(
            token, runtime_api_token(connection_secret, real_token)
        ):
            return None
        return real_token, connection.organization_id

    def _remember_file(self, connection_id: UUID, response: ProxyResponse) -> None:
        result = response.body.get("result") if response.status_code == 200 else None
        file_path = result.get("file_path") if isinstance(result, dict) else None
        if isinstance(file_path, str):
            with self._files_lock:
                now = time.monotonic()
                self._files = {key: expiry for key, expiry in self._files.items() if expiry > now}
                self._files[(connection_id, file_path)] = now + _FILE_LINK_SECONDS

    def _was_shown(self, connection_id: UUID, file_path: str) -> bool:
        with self._files_lock:
            expiry = self._files.get((connection_id, file_path))
        return expiry is not None and expiry > time.monotonic()

    @staticmethod
    def _named_chats(params: dict[str, Any]) -> set[int] | None:
        """Every chat a call names, nested ones included, or None when one is not a private chat id."""
        values = [params[name] for name in _CHAT_FIELDS if name in params]
        if "reply_parameters" in params:
            # A reply may quote a message from another chat the bot is in, which
            # with a shared bot means another Organization's user.
            reply = params["reply_parameters"]
            if isinstance(reply, str):
                try:
                    reply = json.loads(reply)
                except ValueError:
                    return None
            if not isinstance(reply, dict):
                return None
            if "chat_id" in reply:
                values.append(reply["chat_id"])
        chats: set[int] = set()
        for value in values:
            if isinstance(value, bool) or not _CHAT_ID.fullmatch(str(value)):
                return None
            chats.add(int(value))
        return chats

    def _get_me(self, real_token: str) -> ProxyResponse:
        if self._bot is None:
            response = self._forward(real_token, "getMe", BotApiRequest(params={}))
            if response.status_code != 200 or not response.body.get("ok"):
                return response
            self._bot = response.body
        return ProxyResponse(200, self._bot)

    def _forward(self, real_token: str, method: str, request: BotApiRequest) -> ProxyResponse:
        """Send Telegram a call rebuilt from exactly what was read and checked, never the bytes received."""
        url = f"{_TELEGRAM}/bot{real_token}/{method}"
        try:
            if request.encoding == "multipart":
                response = self.client.post(
                    url,
                    data={key: str(value) for key, value in request.params.items()},
                    files=[(f.field, (f.filename, f.content, f.content_type)) for f in request.files],
                )
            elif request.encoding == "form":
                response = self.client.post(
                    url, content=urlencode(request.params).encode(), headers={"Content-Type": _FORM}
                )
            elif request.params:
                response = self.client.post(
                    url, content=json.dumps(request.params).encode(), headers={"Content-Type": _JSON}
                )
            else:
                response = self.client.post(url)
        except httpx.HTTPError as exc:
            # httpx errors carry the URL, and with it the real token.
            logger.warning("Agent Barn Telegram proxy could not reach Telegram (%s)", type(exc).__name__)
            return _error(502, "Bad Gateway: Telegram is unreachable")
        try:
            payload = response.json()
        except ValueError:
            return _error(502, "Bad Gateway: unexpected answer from Telegram")
        return ProxyResponse(response.status_code, payload if isinstance(payload, dict) else {"ok": False})
