import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from injector import inject, singleton

from api.core.config import Config
from api.domains.communications.agentbarn_telegram_forwarder import AgentBarnTelegramForwarder
from api.domains.communications.agentbarn_telegram_processor import AgentBarnTelegramUpdateProcessor
from api.domains.communications.agentbarn_telegram_repository import AgentBarnTelegramRepository
from api.domains.communications.plugins.agentbarn_telegram import AgentBarnTelegramPlatformPlugin
from api.infrastructure.telegram.client import TelegramPollError, get_updates

logger = logging.getLogger(__name__)

# Telegram holds a long poll open for up to this long when nothing arrives.
_POLL_TIMEOUT_SECONDS = 25
_IDLE_SECONDS = 5.0
# Forwarding re-checks this often for retries that came due, and sooner when woken.
_FORWARD_INTERVAL_SECONDS = 1.0
# Updates are processed in chunks, renewing the lease before each, so a long
# pass never outlives it and overlaps a replica that took over.
_PROCESS_CHUNK = 25
_BACKOFF_INITIAL_SECONDS = 1.0
_BACKOFF_MAX_SECONDS = 60.0
# Private chats only: messages, their edits, button presses (including runtime
# approvals), and the user blocking or unblocking the bot.
_ALLOWED_UPDATES = ["message", "edited_message", "callback_query", "my_chat_member"]


@inject
@singleton
@dataclass
class AgentBarnTelegramIngress:
    """Poll Agent Barn's shared bot from exactly one Communications replica.

    Each batch is stored before the next poll's offset tells Telegram it was
    received, so a crash between the two re-delivers the batch instead of
    losing it, and storage ignores the repeats.
    """

    config: Config
    repository: AgentBarnTelegramRepository
    processor: AgentBarnTelegramUpdateProcessor
    forwarder: AgentBarnTelegramForwarder
    offset: int | None = field(default=None, init=False)
    owner_id: str = field(default_factory=lambda: str(uuid4()), init=False)
    # Forwarding runs only on the replica that polls, keeping each user's updates in order.
    holds_lease: bool = field(default=False, init=False)
    _forward_wake: asyncio.Event = field(default_factory=asyncio.Event, init=False)

    def should_poll(self, *, owner: str) -> bool:
        self.holds_lease = AgentBarnTelegramPlatformPlugin(self.config).is_offered() and (
            self.repository.claim_ingress_lease(owner, now=datetime.now(UTC))
        )
        if not self.holds_lease:
            # Another replica may confirm updates while this one waits; resume
            # from what Telegram still holds rather than a remembered offset.
            self.offset = None
        return self.holds_lease

    def wake_forwarder(self) -> None:
        self._forward_wake.set()

    async def forward_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            if self.holds_lease:
                try:
                    await asyncio.to_thread(self.forwarder.forward_due)
                except Exception as exc:
                    logger.warning("Agent Barn Telegram forwarding failed (%s)", type(exc).__name__)
            try:
                await asyncio.wait_for(self._forward_wake.wait(), timeout=_FORWARD_INTERVAL_SECONDS)
            except TimeoutError:
                pass
            self._forward_wake.clear()

    async def poll_once(self, client: httpx.AsyncClient) -> None:
        updates = await get_updates(
            client,
            self.config.agentbarn_telegram_bot_token.strip(),
            offset=self.offset,
            timeout_seconds=_POLL_TIMEOUT_SECONDS,
            allowed_updates=_ALLOWED_UPDATES,
        )
        if not updates:
            return
        await asyncio.to_thread(self.repository.store_updates, updates)
        update_ids = [update["update_id"] for update in updates if isinstance(update.get("update_id"), int)]
        if update_ids:
            self.offset = max(update_ids) + 1

    async def cycle(self, client: httpx.AsyncClient) -> None:
        """Poll once, then act on everything stored, including leftovers from before a restart.

        A batch stored after the lease was lost is left for the replica that now holds it.
        """
        await self.poll_once(client)
        while await asyncio.to_thread(self.should_poll, owner=self.owner_id):
            processed = await asyncio.to_thread(self.processor.process_pending, limit=_PROCESS_CHUNK)
            if processed < _PROCESS_CHUNK:
                break
        if self.holds_lease:
            self.wake_forwarder()

    async def run(self, stop: asyncio.Event) -> None:
        backoff = _BACKOFF_INITIAL_SECONDS
        forwarding = asyncio.create_task(self.forward_loop(stop), name="agentbarn-telegram-forwarding")
        try:
            async with httpx.AsyncClient(timeout=_POLL_TIMEOUT_SECONDS + 10) as client:
                while not stop.is_set():
                    try:
                        if not await asyncio.to_thread(self.should_poll, owner=self.owner_id):
                            await _wait(stop, _IDLE_SECONDS)
                            continue
                        await self.cycle(client)
                        backoff = _BACKOFF_INITIAL_SECONDS
                    except Exception as exc:
                        # TelegramPollError text is token-free; anything else is reported by type only.
                        detail = str(exc) if isinstance(exc, TelegramPollError) else type(exc).__name__
                        logger.warning("Agent Barn Telegram polling failed; retrying in %.0fs: %s", backoff, detail)
                        await _wait(stop, backoff)
                        backoff = min(backoff * 2, _BACKOFF_MAX_SECONDS)
        finally:
            self.holds_lease = False
            forwarding.cancel()
            await asyncio.gather(forwarding, return_exceptions=True)
            await asyncio.to_thread(self.repository.release_ingress_lease, self.owner_id)


async def _wait(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass
