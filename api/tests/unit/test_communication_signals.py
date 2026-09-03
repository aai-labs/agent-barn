import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from redis.exceptions import TimeoutError as RedisTimeoutError

from api.core.config import Config
from api.infrastructure.communication_signals import (
    CommunicationSignal,
    CommunicationSignalBus,
    CommunicationSignalType,
)


def _bus() -> tuple[CommunicationSignalBus, Mock]:
    bus = CommunicationSignalBus(cast(Config, SimpleNamespace(redis_url="redis://unused")))
    client = Mock()
    bus._client = client
    return bus, client


def _async_bus() -> tuple[CommunicationSignalBus, AsyncMock]:
    bus, _ = _bus()
    client = AsyncMock()
    bus._async_client = client
    return bus, client


def test_publish_uses_agent_scoped_content_free_stream() -> None:
    bus, client = _bus()
    pipeline = client.pipeline.return_value
    agent_id = uuid4()
    delivery_id = uuid4()

    bus.publish(
        agent_id,
        CommunicationSignal(
            type=CommunicationSignalType.DELIVERY_CANCELLED,
            delivery_id=delivery_id,
        ),
    )

    key = f"agentbarn:communications:agent:{agent_id}"
    pipeline.xadd.assert_called_once_with(
        key,
        {"type": "delivery_cancelled", "delivery_id": str(delivery_id)},
        maxlen=1_000,
        approximate=True,
    )
    pipeline.expire.assert_called_once_with(key, 86_400)
    pipeline.execute.assert_called_once_with()


def test_cursor_then_wait_decodes_valid_signals_and_skips_malformed_entries() -> None:
    bus, client = _bus()
    agent_id = uuid4()
    delivery_id = uuid4()
    key = f"agentbarn:communications:agent:{agent_id}"
    client.xrevrange.return_value = [("10-0", {"type": "delivery_available"})]
    client.xread.return_value = [
        (
            key,
            [
                ("11-0", {"type": "delivery_available", "delivery_id": str(delivery_id)}),
                ("12-0", {"type": "unknown"}),
            ],
        )
    ]

    cursor = bus.latest_cursor(agent_id)
    next_cursor, signals = bus.wait(agent_id, cursor, timeout_seconds=3)

    assert cursor == "10-0"
    assert next_cursor == "12-0"
    assert signals == [
        CommunicationSignal(
            type=CommunicationSignalType.DELIVERY_AVAILABLE,
            delivery_id=delivery_id,
        )
    ]
    client.xread.assert_called_once_with({key: "10-0"}, count=100, block=3_000)


def test_wait_treats_the_redis_socket_timeout_as_a_heartbeat() -> None:
    bus, client = _bus()
    agent_id = uuid4()
    client.xread.side_effect = RedisTimeoutError("timed out")

    next_cursor, signals = bus.wait(agent_id, "10-0")

    assert next_cursor == "10-0"
    assert signals == []


def test_async_cursor_then_wait_decodes_valid_signals_and_skips_malformed_entries() -> None:
    bus, client = _async_bus()
    agent_id = uuid4()
    delivery_id = uuid4()
    key = f"agentbarn:communications:agent:{agent_id}"
    client.xrevrange.return_value = [("10-0", {"type": "delivery_available"})]
    client.xread.return_value = [
        (
            key,
            [
                ("11-0", {"type": "delivery_available", "delivery_id": str(delivery_id)}),
                ("12-0", {"type": "unknown"}),
            ],
        )
    ]

    async def read_signals() -> tuple[str, str, list[CommunicationSignal]]:
        cursor = await bus.latest_cursor_async(agent_id)
        next_cursor, signals = await bus.wait_async(agent_id, cursor, timeout_seconds=3)
        return cursor, next_cursor, signals

    cursor, next_cursor, signals = asyncio.run(read_signals())

    assert cursor == "10-0"
    assert next_cursor == "12-0"
    assert signals == [
        CommunicationSignal(
            type=CommunicationSignalType.DELIVERY_AVAILABLE,
            delivery_id=delivery_id,
        )
    ]
    client.xrevrange.assert_awaited_once_with(key, count=1)
    client.xread.assert_awaited_once_with({key: "10-0"}, count=100, block=3_000)


def test_async_wait_treats_the_redis_socket_timeout_as_a_heartbeat() -> None:
    bus, client = _async_bus()
    agent_id = uuid4()
    client.xread.side_effect = RedisTimeoutError("timed out")

    next_cursor, signals = asyncio.run(bus.wait_async(agent_id, "10-0"))

    assert next_cursor == "10-0"
    assert signals == []
