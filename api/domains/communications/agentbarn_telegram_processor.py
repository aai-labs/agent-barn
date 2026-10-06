import enum
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.communications.agentbarn_telegram_repository import (
    AgentBarnTelegramRepository,
    LinkTokenOutcome,
)
from api.domains.communications.agentbarn_telegram_service import AgentBarnTelegramService
from api.domains.communications.models import AgentBarnTelegramUpdate
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.telegram.client import send_message

logger = logging.getLogger(__name__)

# "/start <token>", optionally addressed as "/start@BotName <token>", as Telegram
# sends it when someone opens a t.me/<bot>?start=<token> deep link.
_START_WITH_TOKEN = re.compile(r"^/start(?:@\w+)?\s+([A-Za-z0-9_-]{1,64})\s*$")
_ROUTED_MESSAGE_KEYS = ("message", "edited_message")


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
    """Messages Agent Barn's shared bot sends on its own behalf."""

    config: Config

    def send(self, chat_id: int, text: str) -> None:
        send_message(self.config.agentbarn_telegram_bot_token.strip(), str(chat_id), text)


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

    def process_pending(self, *, limit: int = 100) -> int:
        updates = self.repository.received_updates(limit=limit)
        for update in updates:
            try:
                self._process(update)
            except Exception as exc:
                # Left RECEIVED and retried on the next pass; content stays out of the log.
                logger.warning("Agent Barn Telegram update %s failed (%s)", update.update_id, type(exc).__name__)
        return len(updates)

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
        self._reply(
            chat_id,
            f"Hi! To talk to an agent here, sign up at {self.config.web_app_url} and connect Telegram from there.",
        )
        return False

    def _reply(self, chat_id: int, text: str) -> None:
        try:
            self.bot.send(chat_id, text)
        except Exception as exc:
            logger.warning("Agent Barn Telegram reply failed (%s)", type(exc).__name__)
