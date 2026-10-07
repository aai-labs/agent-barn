import threading
import time
from dataclasses import dataclass, field
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config


@dataclass
class _Bucket:
    rate: float
    capacity: float
    tokens: float
    updated_at: float

    def refill(self, now: float) -> None:
        self.tokens = min(self.capacity, self.tokens + (now - self.updated_at) * self.rate)
        self.updated_at = now

    def wait(self) -> float:
        """Seconds until one call fits; zero when it fits now."""
        return 0.0 if self.tokens >= 1 else (1 - self.tokens) / self.rate


@dataclass
class TelegramRateLimiter:
    """Keep the shared bot inside Telegram's limits, and every Organization inside its share.

    Telegram limits a bot as a whole, so one busy Organization could otherwise
    exhaust the bot for everyone or get it throttled. Each call must fit both
    the bot's budget and its Organization's; a refused call uses neither. The
    state is per process, which holds while one Communications replica polls
    and proxies.
    """

    bot_per_second: float
    organization_per_second: float
    _bot: _Bucket | None = field(default=None, init=False)
    _organizations: dict[UUID, _Bucket] = field(default_factory=dict, init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def acquire(self, organization_id: UUID, *, now: float) -> float:
        """Take one call's budget and return 0, or return how long to wait and take nothing."""
        with self._lock:
            if self._bot is None:
                self._bot = self._new_bucket(self.bot_per_second, now)
            organization = self._organizations.get(organization_id)
            if organization is None:
                organization = self._organizations[organization_id] = self._new_bucket(
                    self.organization_per_second, now
                )
            self._bot.refill(now)
            organization.refill(now)
            wait = max(self._bot.wait(), organization.wait())
            if wait > 0:
                return wait
            self._bot.tokens -= 1
            organization.tokens -= 1
            return 0.0

    @staticmethod
    def _new_bucket(per_second: float, now: float) -> _Bucket:
        # A full second's budget may be spent at once, then refills steadily.
        return _Bucket(rate=per_second, capacity=max(per_second, 1.0), tokens=max(per_second, 1.0), updated_at=now)


# The bot's own messages (sign-up prompts, link confirmations, notices) have no
# Organization; they draw on this bucket and on the bot-wide budget like any call.
_PLATFORM = UUID(int=0)


@inject
@singleton
class AgentBarnTelegramRateLimits:
    """The one budget for everything sent through Agent Barn's shared bot.

    Agents' proxied calls and the bot's own replies share it, so a flood of
    strangers cannot spend the bot's Telegram allowance that every Organization
    depends on.
    """

    def __init__(self, config: Config) -> None:
        self._limiter = TelegramRateLimiter(
            bot_per_second=config.agentbarn_telegram_bot_rate_per_second,
            organization_per_second=config.agentbarn_telegram_organization_rate_per_second,
        )

    def acquire_for_organization(self, organization_id: UUID | None, *, now: float | None = None) -> float:
        """Take one call's budget for an Organization (None for the bot itself) and return 0, or the wait."""
        return self._limiter.acquire(organization_id or _PLATFORM, now=time.monotonic() if now is None else now)
