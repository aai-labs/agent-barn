import enum
import json
from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

from injector import inject, singleton
from redis import Redis
from redis.exceptions import TimeoutError as RedisTimeoutError

from api.core.config import Config

_SIGNAL_STREAM_PREFIX = "agentbarn:communications:agent"
_SIGNAL_STREAM_MAX_LENGTH = 1_000
_SIGNAL_STREAM_TTL_SECONDS = 86_400
_SIGNAL_SOCKET_TIMEOUT_SECONDS = 20


class CommunicationSignalType(str, enum.Enum):
    DELIVERY_AVAILABLE = "delivery_available"
    DELIVERY_CANCELLED = "delivery_cancelled"
    MESSAGE_CHANGED = "message_changed"


@dataclass(frozen=True)
class CommunicationSignal:
    type: CommunicationSignalType
    delivery_id: UUID | None = None

    def as_json(self) -> str:
        return json.dumps(
            {
                "type": self.type.value,
                **({"delivery_id": str(self.delivery_id)} if self.delivery_id is not None else {}),
            }
        )


@inject
@singleton
@dataclass
class CommunicationSignalBus:
    """Redis wakeups for durable Communications state.

    PostgreSQL remains authoritative. Redis Streams only bridge commits to
    long-lived runtime and browser connections; callers always replay durable
    state after taking a stream cursor, so duplicate wakeups are harmless.
    """

    config: Config
    _client: Redis = field(init=False)

    def __post_init__(self) -> None:
        # redis-py 8 defaults maintenance-enabled connections to a five-second
        # socket timeout. XREAD intentionally blocks for up to 15 seconds, so
        # give the blocking command a larger transport timeout.
        self._client = Redis.from_url(
            self.config.redis_url,
            decode_responses=True,
            socket_timeout=_SIGNAL_SOCKET_TIMEOUT_SECONDS,
        )

    @staticmethod
    def _stream_key(agent_id: UUID) -> str:
        return f"{_SIGNAL_STREAM_PREFIX}:{agent_id}"

    def publish(self, agent_id: UUID, signal: CommunicationSignal) -> None:
        key = self._stream_key(agent_id)
        fields: dict[str, str] = {"type": signal.type.value}
        if signal.delivery_id is not None:
            fields["delivery_id"] = str(signal.delivery_id)
        pipeline = self._client.pipeline(transaction=False)
        pipeline.xadd(
            key,
            cast(dict[Any, Any], fields),
            maxlen=_SIGNAL_STREAM_MAX_LENGTH,
            approximate=True,
        )
        pipeline.expire(key, _SIGNAL_STREAM_TTL_SECONDS)
        pipeline.execute()

    def latest_cursor(self, agent_id: UUID) -> str:
        entries = self._client.xrevrange(self._stream_key(agent_id), count=1)
        if not entries:
            return "0-0"
        cursor = entries[0][0]
        return cursor.decode() if isinstance(cursor, bytes) else str(cursor)

    def wait(
        self,
        agent_id: UUID,
        cursor: str,
        *,
        timeout_seconds: int = 15,
    ) -> tuple[str, list[CommunicationSignal]]:
        try:
            entries = cast(
                list[tuple[str, list[tuple[str, dict[str, str]]]]],
                self._client.xread(
                    {self._stream_key(agent_id): cursor},
                    count=100,
                    block=timeout_seconds * 1_000,
                ),
            )
        except RedisTimeoutError:
            # A transport timeout is equivalent to an empty blocking read for
            # stream consumers: preserve the cursor and let the caller emit a
            # heartbeat rather than tearing down the SSE response.
            return cursor, []
        signals: list[CommunicationSignal] = []
        next_cursor = cursor
        for _, messages in entries:
            for message_id, fields in messages:
                next_cursor = message_id
                try:
                    signal_type = CommunicationSignalType(fields["type"])
                    delivery_id = UUID(fields["delivery_id"]) if fields.get("delivery_id") else None
                except KeyError, TypeError, ValueError:
                    continue
                signals.append(CommunicationSignal(type=signal_type, delivery_id=delivery_id))
        return next_cursor, signals
