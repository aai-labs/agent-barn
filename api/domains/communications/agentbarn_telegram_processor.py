import enum
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.communications.agentbarn_telegram_rate_limit import AgentBarnTelegramRateLimits
from api.domains.communications.agentbarn_telegram_repository import (
    AgentBarnTelegramRepository,
    LinkTokenOutcome,
)
from api.domains.communications.agentbarn_telegram_service import AgentBarnTelegramService
from api.domains.communications.models import AgentBarnTelegramUpdate
from api.domains.rbac.catalog import PermissionKey

logger = logging.getLogger(__name__)

# "/start <token>", optionally addressed as "/start@BotName <token>", as Telegram
# sends it when someone opens a t.me/<bot>?start=<token> deep link.
_START_WITH_TOKEN = re.compile(r"^/start(?:@\w+)?\s+([A-Za-z0-9_-]{1,64})\s*$")
_ROUTED_MESSAGE_KEYS = ("message", "edited_message")
# An update that fails this many passes is given up rather than retried forever.
_MAX_PROCESSING_ATTEMPTS = 5
# Someone who is not linked hears how to sign up at most this often.
_SIGN_UP_REPLY_COOLDOWN_SECONDS = 600
# A message the bot must send waits at most this long for the shared budget.
_ESSENTIAL_WAIT_SECONDS = 2.0
_SEND_TIMEOUT_SECONDS = 5


class UpdateKind(enum.Enum):
    LINK = "link"
    ROUTE = "route"
    BLOCKED = "blocked"
    IGNORE = "ignore"


@dataclass(frozen=True)
class ClassifiedUpdate:
    kind: UpdateKind
    telegram_user_id: int | None = None
    chat_id: int | None = None
    first_name: str | None = None
    username: str | None = None
    link_token: str | None = None


def _sender(sender: Any) -> tuple[int, str | None, str | None] | None:
    if not isinstance(sender, dict) or sender.get("is_bot") or not isinstance(sender.get("id"), int):
        return None
    return sender["id"], sender.get("first_name"), sender.get("username")


def _private_chat_id(chat: Any) -> int | None:
    if isinstance(chat, dict) and chat.get("type") == "private" and isinstance(chat.get("id"), int):
        return chat["id"]
    return None


def classify_update(payload: dict[str, Any]) -> ClassifiedUpdate:
    """Decide what one shared-bot update means. Only private chats are acted on."""
    for key in _ROUTED_MESSAGE_KEYS:
        message = payload.get(key)
        if isinstance(message, dict):
            sender = _sender(message.get("from"))
            chat_id = _private_chat_id(message.get("chat"))
            if sender is None or chat_id is None:
                return ClassifiedUpdate(UpdateKind.IGNORE)
            user_id, first_name, username = sender
            text = message.get("text") if key == "message" else None
            match = _START_WITH_TOKEN.match(text) if isinstance(text, str) else None
            return ClassifiedUpdate(
                UpdateKind.LINK if match else UpdateKind.ROUTE,
                telegram_user_id=user_id,
                chat_id=chat_id,
                first_name=first_name,
                username=username,
                link_token=match.group(1) if match else None,
            )

    callback = payload.get("callback_query")
    if isinstance(callback, dict):
        sender = _sender(callback.get("from"))
        message = callback.get("message")
        chat_id = _private_chat_id(message.get("chat")) if isinstance(message, dict) else None
        if sender is None or chat_id is None:
            return ClassifiedUpdate(UpdateKind.IGNORE)
        user_id, first_name, username = sender
        return ClassifiedUpdate(
            UpdateKind.ROUTE, telegram_user_id=user_id, chat_id=chat_id, first_name=first_name, username=username
        )

    membership = payload.get("my_chat_member")
    if isinstance(membership, dict):
        sender = _sender(membership.get("from"))
        chat_id = _private_chat_id(membership.get("chat"))
        new_status = (membership.get("new_chat_member") or {}).get("status")
        if sender is not None and chat_id is not None and new_status == "kicked":
            return ClassifiedUpdate(UpdateKind.BLOCKED, telegram_user_id=sender[0], chat_id=chat_id)

    return ClassifiedUpdate(UpdateKind.IGNORE)


@inject
@singleton
@dataclass
class AgentBarnTelegramBot:
    """Messages Agent Barn's shared bot sends on its own behalf.

    They draw on the same budget as Agents' calls, and are tried once without
    sleeping retries, so they can neither spend the bot's Telegram allowance nor
    stall update processing.
    """

    config: Config
    limits: AgentBarnTelegramRateLimits
    client: httpx.Client = field(default_factory=lambda: httpx.Client(timeout=_SEND_TIMEOUT_SECONDS), init=False)

    def send(self, chat_id: int, text: str, *, essential: bool = True) -> bool:
        """Send one message; False when it was skipped for budget or failed.

        Courtesy messages are skipped while the budget is spent; essential ones
        (link confirmations, delivery notices) wait briefly for it.
        """
        wait = self.limits.acquire_for_organization(None)
        if wait > 0 and essential and wait <= _ESSENTIAL_WAIT_SECONDS:
            time.sleep(wait)
            wait = self.limits.acquire_for_organization(None)
        if wait > 0:
            logger.info("Agent Barn Telegram bot message skipped: rate budget spent")
            return False
        token = self.config.agentbarn_telegram_bot_token.strip()
        try:
            response = self.client.post(
                f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": text}
            )
        except httpx.HTTPError as exc:
            # httpx errors carry the URL, and with it the token.
            logger.warning("Agent Barn Telegram bot message failed (%s)", type(exc).__name__)
            return False
        if not response.is_success:
            logger.warning("Agent Barn Telegram bot message refused (HTTP %s)", response.status_code)
            return False
        return True


@inject
@singleton
@dataclass
class AgentBarnTelegramUpdateProcessor:
    """Act on stored shared-bot updates: link accounts, answer strangers, queue the rest.

    Runs only on the replica holding the polling lease, so updates are handled
    one at a time in Telegram's order.
    """

    config: Config
    repository: AgentBarnTelegramRepository
    links: AgentBarnTelegramService
    authorization: AgentAuthorization
    bot: AgentBarnTelegramBot
    # When each unlinked sender was last told how to sign up (per process).
    _sign_up_replies: dict[int, float] = field(default_factory=dict, init=False)
    _sign_up_lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def process_pending(self, *, limit: int = 100) -> int:
        """Process up to `limit` received updates; return how many were done with.

        Failed and held-back updates do not count, so a caller that keeps going
        while a pass is full does not retry a failure straight away.
        """
        updates = self.repository.received_updates(limit=limit)
        done = 0
        # A user's later updates wait behind one of theirs that failed, keeping their order.
        held_back: set[int] = set()
        for update in updates:
            user_id = classify_update(update.payload or {}).telegram_user_id
            if user_id is not None and user_id in held_back:
                continue
            try:
                self._process(update)
                done += 1
            except Exception as exc:
                # Content stays out of the log.
                logger.warning("Agent Barn Telegram update %s failed (%s)", update.update_id, type(exc).__name__)
                if user_id is not None:
                    held_back.add(user_id)
                self._record_failure(update)
        return done

    def _record_failure(self, update: AgentBarnTelegramUpdate) -> None:
        try:
            attempts = self.repository.record_processing_failure(update.update_id)
            if attempts >= _MAX_PROCESSING_ATTEMPTS:
                logger.warning("Agent Barn Telegram update %s given up after %s attempts", update.update_id, attempts)
                self.repository.settle_update(update.update_id)
        except Exception as exc:
            logger.warning(
                "Agent Barn Telegram update %s failure not recorded (%s)", update.update_id, type(exc).__name__
            )

    def _process(self, update: AgentBarnTelegramUpdate) -> None:
        classified = classify_update(update.payload or {})
        user_id, chat_id = classified.telegram_user_id, classified.chat_id
        if classified.kind == UpdateKind.LINK and user_id is not None and chat_id is not None:
            self._link(classified, user_id, chat_id)
        elif classified.kind == UpdateKind.BLOCKED and user_id is not None:
            self.repository.end_active_link(user_id, now=datetime.now(UTC))
        elif (
            classified.kind == UpdateKind.ROUTE
            and user_id is not None
            and chat_id is not None
            and self._queue(update.update_id, user_id, chat_id)
        ):
            # Queued for the Agent; its content is kept until forwarded.
            return
        self.repository.settle_update(update.update_id)

    def _link(self, classified: ClassifiedUpdate, user_id: int, chat_id: int) -> None:
        assert classified.link_token is not None
        result = self.links.consume_link_token(
            classified.link_token, telegram_user_id=user_id, telegram_username=classified.username
        )
        if result.outcome == LinkTokenOutcome.EXPIRED:
            self._reply(chat_id, "This link has expired. Go back to Agent Barn for a fresh one.")
            return
        if result.outcome != LinkTokenOutcome.LINKED or result.link is None:
            self._reply(
                chat_id, "This link has already been used or isn't valid. Go back to Agent Barn for a fresh one."
            )
            return
        replaced = result.replaced_link
        names = self.repository.agent_names(
            [result.link.agent_id, *([replaced.agent_id] if replaced is not None else [])]
        )
        agent_name = names.get(result.link.agent_id, "your agent")
        if replaced is not None and replaced.agent_id != result.link.agent_id:
            previous_name = names.get(replaced.agent_id, "your previous agent")
            self._reply(
                chat_id,
                f"You're now talking to {agent_name}. You won't get replies from {previous_name} here anymore.",
            )
            return
        self._reply(
            chat_id,
            f"Hi {classified.first_name or 'there'}! You're linked to {agent_name}. Send a message to get started.",
        )

    def _queue(self, update_id: int, user_id: int, chat_id: int) -> bool:
        link = self.repository.find_routable_link(user_id)
        if link is not None and self.authorization.membership_has_permission(
            link.linked_by_membership_id, link.agent_id, PermissionKey.AGENT_UPDATE
        ):
            self.repository.queue_update(
                update_id, telegram_user_id=user_id, agent_id=link.agent_id, connection_id=link.connection_id
            )
            return True
        if link is not None:
            # The Member who linked this account lost access to the Agent.
            self.repository.end_active_link(user_id, now=datetime.now(UTC))
        if self._sign_up_reply_due(user_id):
            self._reply(
                chat_id,
                f"Hi! To talk to an agent here, sign up at {self.config.web_app_url} and connect Telegram from there.",
                essential=False,
            )
        return False

    def _sign_up_reply_due(self, user_id: int) -> bool:
        now = time.monotonic()
        with self._sign_up_lock:
            last = self._sign_up_replies.get(user_id)
            if last is not None and now - last < _SIGN_UP_REPLY_COOLDOWN_SECONDS:
                return False
            self._sign_up_replies = {
                key: value
                for key, value in self._sign_up_replies.items()
                if now - value < _SIGN_UP_REPLY_COOLDOWN_SECONDS
            }
            self._sign_up_replies[user_id] = now
            return True

    def _reply(self, chat_id: int, text: str, *, essential: bool = True) -> None:
        try:
            self.bot.send(chat_id, text, essential=essential)
        except Exception as exc:
            logger.warning("Agent Barn Telegram reply failed (%s)", type(exc).__name__)
