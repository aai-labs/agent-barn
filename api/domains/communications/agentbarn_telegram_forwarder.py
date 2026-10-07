import enum
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import AgentStatus
from api.domains.communications.agentbarn_telegram_processor import AgentBarnTelegramBot
from api.domains.communications.agentbarn_telegram_repository import AgentBarnTelegramRepository
from api.domains.communications.models import AgentBarnTelegramUpdate
from api.domains.communications.plugins.agentbarn_telegram import runtime_webhook_secret
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.crypto import decrypt_token

logger = logging.getLogger(__name__)

# Telegram itself keeps undelivered updates for a day; so do we.
HOLD_WINDOW = timedelta(hours=24)
# A pod that is merely starting usually answers within this; only then is the user told.
WAKING_NOTICE_AFTER = timedelta(seconds=10)
_RETRY_MAX_SECONDS = 60
_OFFLINE_RECHECK = timedelta(seconds=30)
_REQUEST_TIMEOUT_SECONDS = 10
# A pod that is down usually refuses fast; one that accepts but hangs costs the full
# timeout, so users are delivered on parallel workers, each user on one worker.
_CONNECT_TIMEOUT_SECONDS = 2
_WORKERS = 8
_BATCH = 100
_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
# Answers from the cluster or the pod while it is still coming up.
_NOT_YET_SERVING = frozenset({502, 503, 504})


class _Delivery(enum.Enum):
    ACCEPTED = "accepted"
    # Not reachable yet, as when the pod is starting.
    UNREACHABLE = "unreachable"
    # Reachable but refused it; never described to the user as starting up.
    REJECTED = "rejected"


_WAKING_UP = "Your agent is waking up. I'll pass your message on in a moment."
_OFFLINE = "This agent is offline right now. I'll pass your message on when it's back."


def _dropped_notice(count: int) -> str:
    # A drop means delivery failed for the whole hold window, whatever the cause,
    # so the note says exactly that rather than guessing the Agent was stopped.
    if count == 1:
        return "I couldn't reach your agent for over a day, so your message wasn't delivered. Please send it again."
    return (
        f"I couldn't reach your agent for over a day, so your {count} messages weren't delivered. "
        "Please send them again."
    )


@inject
@singleton
@dataclass
class AgentBarnTelegramForwarder:
    """Deliver queued shared-bot updates to each Agent's own Telegram webhook.

    Each Telegram user's updates go out oldest first, and a failed one holds
    back that user's later ones, never anyone else's. The request carries the
    Connection's derived secret, which the runtime's webhook checks, so the
    pod accepts updates only from Agent Barn.
    """

    config: Config
    repository: AgentBarnTelegramRepository
    bot: AgentBarnTelegramBot
    authorization: AgentAuthorization
    client: httpx.Client = field(
        default_factory=lambda: httpx.Client(
            timeout=httpx.Timeout(_REQUEST_TIMEOUT_SECONDS, connect=_CONNECT_TIMEOUT_SECONDS)
        ),
        init=False,
    )

    def forward_due(self, *, now: datetime | None = None) -> int:
        now = now or datetime.now(UTC)
        for user_id, count in self.repository.drop_expired(received_before=now - HOLD_WINDOW).items():
            self._reply(user_id, _dropped_notice(count))
        heads = self.repository.queue_heads(now=now, limit=_BATCH)
        if not heads:
            return 0
        with ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="agentbarn-telegram-forward") as pool:
            return sum(pool.map(lambda head: self._deliver_user_queue(head, now), heads))

    def _deliver_user_queue(self, head: AgentBarnTelegramUpdate, now: datetime) -> int:
        """Deliver one user's updates oldest first, stopping at the first that is not accepted."""
        forwarded = 0
        update: AgentBarnTelegramUpdate | None = head
        try:
            while update is not None and self._due(update, now) and self._deliver(update, now):
                forwarded += 1
                assert update.telegram_user_id is not None
                update = self.repository.queue_head_for_user(update.telegram_user_id)
        except Exception as exc:
            # One user's failure must not stop the other workers; the update stays queued.
            logger.warning("Agent Barn Telegram delivery failed (%s)", type(exc).__name__)
        return forwarded

    @staticmethod
    def _due(update: AgentBarnTelegramUpdate, now: datetime) -> bool:
        return update.next_attempt_at is None or update.next_attempt_at <= now

    def _deliver(self, update: AgentBarnTelegramUpdate, now: datetime) -> bool:
        """Try one update; True when the Agent accepted it."""
        assert update.agent_id is not None and update.connection_id is not None
        assert update.telegram_user_id is not None
        target = self.repository.forward_target(update.agent_id, update.connection_id, update.telegram_user_id)
        if target is None or not target.in_use or target.link is None:
            # The Connection is gone, or the sender was unlinked or switched Agents
            # since this was queued; it must not reach the Agent after all.
            self.repository.drop(update.update_id)
            return False
        if not self.authorization.membership_has_permission(
            target.link.linked_by_membership_id, update.agent_id, PermissionKey.AGENT_UPDATE
        ):
            # The Member who linked this sender lost access while it waited.
            self.repository.end_link_for_connection(update.connection_id, update.telegram_user_id, now=now)
            self.repository.drop(update.update_id)
            return False
        if target.agent_status != AgentStatus.RUNNING:
            if self.repository.claim_notice(update.telegram_user_id, now=now):
                self._reply(update.telegram_user_id, _OFFLINE)
            self.repository.schedule_retry(update.update_id, at=now + _OFFLINE_RECHECK)
            return False
        delivery = self._post(update, target.driver_key_encrypted)
        if delivery == _Delivery.ACCEPTED:
            self.repository.mark_forwarded(update.update_id)
            return True
        if (
            delivery == _Delivery.UNREACHABLE
            and now - update.created_at >= WAKING_NOTICE_AFTER
            and self.repository.claim_notice(update.telegram_user_id, now=now)
        ):
            self._reply(update.telegram_user_id, _WAKING_UP)
        delay = min(2**update.attempt_count, _RETRY_MAX_SECONDS)
        self.repository.schedule_retry(update.update_id, at=now + timedelta(seconds=delay))
        return False

    def _post(self, update: AgentBarnTelegramUpdate, driver_key_encrypted: str) -> _Delivery:
        url = self.config.agentbarn_telegram_runtime_webhook_url.format(
            agent_id=update.agent_id, namespace=self.config.k8s_namespace
        )
        secret = runtime_webhook_secret(decrypt_token(driver_key_encrypted, self.config.agent_token_encryption_key))
        try:
            response = self.client.post(
                url,
                content=json.dumps(update.payload, separators=(",", ":")).encode(),
                headers={"Content-Type": "application/json", _SECRET_HEADER: secret},
            )
        except httpx.HTTPError as exc:
            logger.info("Agent %s Telegram webhook unreachable (%s)", update.agent_id, type(exc).__name__)
            return _Delivery.UNREACHABLE
        if response.is_success:
            return _Delivery.ACCEPTED
        if response.status_code in _NOT_YET_SERVING:
            return _Delivery.UNREACHABLE
        logger.warning("Agent %s Telegram webhook refused an update (HTTP %s)", update.agent_id, response.status_code)
        return _Delivery.REJECTED

    def _reply(self, chat_id: int, text: str) -> None:
        try:
            self.bot.send(chat_id, text)
        except Exception as exc:
            logger.warning("Agent Barn Telegram notice failed (%s)", type(exc).__name__)
