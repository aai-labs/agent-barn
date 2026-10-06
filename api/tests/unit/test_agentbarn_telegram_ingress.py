import asyncio
import json
import logging
from dataclasses import dataclass
from typing import cast
from unittest.mock import Mock, patch

import httpx
import pytest

from api.core.config import Config
from api.domains.communications.agentbarn_telegram_ingress import AgentBarnTelegramIngress
from api.infrastructure.telegram.client import TelegramPollError

_TOKEN = "424242:agentbarn-secret-token"


@dataclass
class BotConfig:
    agentbarn_telegram_bot_token: str = _TOKEN
    agentbarn_telegram_bot_username: str = "AgentBarnTestBot"


def _ingress(
    repository: Mock,
    config: BotConfig | None = None,
    processor: Mock | None = None,
    forwarder: Mock | None = None,
) -> AgentBarnTelegramIngress:
    return AgentBarnTelegramIngress(
        config=cast(Config, config or BotConfig()),
        repository=repository,
        processor=processor or Mock(),
        forwarder=forwarder or Mock(),
    )


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_a_poll_stores_updates_then_confirms_them_on_the_next_poll() -> None:
    requests: list[httpx.Request] = []
    batches = [
        {"ok": True, "result": [{"update_id": 7}, {"update_id": 8}]},
        {"ok": True, "result": []},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=batches.pop(0))

    repository = Mock()
    ingress = _ingress(repository)

    async def exercise() -> None:
        async with _client(handler) as client:
            await ingress.poll_once(client)
            await ingress.poll_once(client)

    asyncio.run(exercise())

    repository.store_updates.assert_called_once_with([{"update_id": 7}, {"update_id": 8}])
    assert requests[0].url.path == f"/bot{_TOKEN}/getUpdates"
    assert "offset" not in requests[0].url.params
    # Telegram treats every update below the offset as delivered, so it moves
    # forward only after the batch is stored.
    assert requests[1].url.params["offset"] == "9"
    assert set(json.loads(requests[0].url.params["allowed_updates"])) == {
        "message",
        "edited_message",
        "callback_query",
        "my_chat_member",
    }


def test_a_batch_that_cannot_be_stored_is_not_confirmed() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 7}]})

    repository = Mock()
    repository.store_updates.side_effect = [RuntimeError("database down"), 1]
    ingress = _ingress(repository)

    async def exercise() -> None:
        async with _client(handler) as client:
            with pytest.raises(RuntimeError):
                await ingress.poll_once(client)
            await ingress.poll_once(client)

    asyncio.run(exercise())

    assert "offset" not in requests[1].url.params


def test_a_failed_poll_never_reveals_the_bot_token(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    ingress = _ingress(Mock())

    async def exercise() -> None:
        async with _client(handler) as client:
            await ingress.poll_once(client)

    with caplog.at_level(logging.DEBUG), pytest.raises(Exception) as raised:
        asyncio.run(exercise())

    assert _TOKEN not in str(raised.value)
    assert "agentbarn-secret-token" not in caplog.text


def test_nothing_is_polled_while_the_shared_bot_is_unconfigured() -> None:
    repository = Mock()
    ingress = _ingress(repository, BotConfig(agentbarn_telegram_bot_token=""))

    assert ingress.should_poll(owner="replica-a") is False
    repository.claim_ingress_lease.assert_not_called()


def test_nothing_is_polled_without_the_lease() -> None:
    repository = Mock()
    repository.claim_ingress_lease.return_value = False

    assert _ingress(repository).should_poll(owner="replica-a") is False


def test_losing_the_lease_forgets_the_offset() -> None:
    # Another replica may have confirmed updates meanwhile; start from what
    # Telegram still holds rather than an offset this replica remembered.
    repository = Mock()
    repository.claim_ingress_lease.side_effect = [True, False, True]
    ingress = _ingress(repository)
    ingress.offset = 42

    assert ingress.should_poll(owner="replica-a") is True
    assert ingress.offset == 42
    assert ingress.should_poll(owner="replica-a") is False
    assert ingress.should_poll(owner="replica-a") is True
    assert ingress.offset is None


def test_httpx_request_logs_redact_bot_tokens(caplog: pytest.LogCaptureFixture) -> None:
    # Importing the ingress module installs the Telegram client's httpx log filter.
    with caplog.at_level(logging.INFO, logger="httpx"):
        logging.getLogger("httpx").info(
            'HTTP Request: %s %s "%s"', "GET", f"https://api.telegram.org/bot{_TOKEN}/getUpdates", "HTTP/1.1 200 OK"
        )

    assert _TOKEN not in caplog.text
    assert "https://api.telegram.org/bot<redacted>/getUpdates" in caplog.text


def test_each_cycle_processes_what_was_stored_including_leftovers() -> None:
    order: list[str] = []
    repository = Mock()
    repository.store_updates.side_effect = lambda updates: order.append("store")
    processor = Mock()
    processor.process_pending.side_effect = lambda: order.append("process")
    batches = [{"ok": True, "result": [{"update_id": 7}]}, {"ok": True, "result": []}]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=batches.pop(0))

    ingress = _ingress(repository, processor=processor)

    async def exercise() -> None:
        async with _client(handler) as client:
            await ingress.cycle(client)
            await ingress.cycle(client)

    asyncio.run(exercise())

    # The second, empty poll still processes anything left from before.
    assert order == ["store", "process", "process"]


def test_the_poller_backs_off_after_a_failure_and_releases_its_lease_on_stop(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = Mock()
    repository.claim_ingress_lease.return_value = True
    ingress = _ingress(repository)
    stop = asyncio.Event()
    cycles: list[str] = []

    async def failing_then_stopping(client: httpx.AsyncClient) -> None:
        cycles.append("cycle")
        if len(cycles) == 1:
            raise TelegramPollError("Telegram getUpdates failed (HTTP 502)")
        stop.set()

    async def exercise() -> None:
        with patch.object(ingress, "cycle", side_effect=failing_then_stopping):
            await asyncio.wait_for(ingress.run(stop), timeout=5)

    with caplog.at_level(logging.WARNING):
        asyncio.run(exercise())

    assert cycles == ["cycle", "cycle"]
    assert "retrying in 1s: Telegram getUpdates failed (HTTP 502)" in caplog.text
    repository.release_ingress_lease.assert_called_once_with(ingress.owner_id)


def test_forwarding_runs_only_on_the_replica_that_holds_the_lease() -> None:
    repository = Mock()
    repository.claim_ingress_lease.return_value = False
    forwarder = Mock()
    ingress = _ingress(repository, forwarder=forwarder)
    stop = asyncio.Event()

    async def exercise() -> int:
        loop = asyncio.create_task(ingress.forward_loop(stop))
        ingress.should_poll(owner="replica-a")
        ingress.wake_forwarder()
        await asyncio.sleep(0.05)
        without_lease = forwarder.forward_due.call_count
        repository.claim_ingress_lease.return_value = True
        ingress.should_poll(owner="replica-a")
        ingress.wake_forwarder()
        await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(loop, timeout=2)
        return without_lease

    without_lease = asyncio.run(exercise())

    assert without_lease == 0
    assert forwarder.forward_due.call_count >= 1
