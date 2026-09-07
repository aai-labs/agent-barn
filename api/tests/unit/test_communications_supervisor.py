import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from hamcrest import assert_that, contains_exactly, contains_string, equal_to, has_properties, is_, not_
from websockets.asyncio.server import ServerConnection, serve

from api.core.config import Config
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationErrorCategory,
    ConnectionObservedStatus,
)
from api.domains.communications.plugins.discord import DiscordPlatformPlugin
from api.domains.communications.repository import _emits_health_event
from api.domains.communications.supervisor import PlatformIngressSupervisor


def test_connection_setup_failure_records_error_health() -> None:
    connection = CommunicationConnection(
        organization_id=uuid4(),
        agent_id=uuid4(),
        platform_key="missing",
        display_name="Broken Connection",
        credentials_encrypted="invalid",
        driver_key_encrypted="invalid",
    )
    connections = Mock()
    plugins = Mock()
    plugins.require.side_effect = KeyError("Unsupported communication platform: missing")
    supervisor = PlatformIngressSupervisor(
        config=cast(Config, SimpleNamespace(agent_token_encryption_key="test-key")),
        connections=connections,
        gateway=Mock(),
        plugins=plugins,
    )

    async def exercise() -> None:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(supervisor._maintain(connection), timeout=0.05)

    asyncio.run(exercise())

    statuses = [call.args[1] for call in connections.record_health.call_args_list]
    assert_that(
        statuses,
        contains_exactly(ConnectionObservedStatus.CONNECTING, ConnectionObservedStatus.ERROR),
    )
    error_call = connections.record_health.call_args_list[-1]
    assert_that(error_call.kwargs["error_code"], equal_to("CONFIGURATION_ERROR"))
    assert_that(error_call.kwargs["error_details"].category.value, equal_to("configuration"))
    assert_that(error_call.kwargs["error_details"].operation, equal_to("ingress_session"))


@pytest.mark.parametrize(
    ("provider_code", "provider_reason", "error_code", "category", "summary"),
    [
        (
            4014,
            "Disallowed intent(s)",
            "CONFIGURATION_ERROR",
            CommunicationErrorCategory.CONFIGURATION,
            (
                "Discord rejected a privileged gateway intent; enable Message Content Intent "
                "in the Discord Developer Portal, then reconnect (4014)"
            ),
        ),
        (
            4013,
            "Invalid intent(s)",
            "CONFIGURATION_ERROR",
            CommunicationErrorCategory.CONFIGURATION,
            (
                "Discord rejected the gateway intent selection; review the configured Discord intents, "
                "then reconnect (4013)"
            ),
        ),
        (
            4004,
            "Authentication failed",
            "AUTHENTICATION_FAILED",
            CommunicationErrorCategory.AUTHENTICATION,
            "Discord rejected the bot token; update this Connection with a valid bot token, then reconnect (4004)",
        ),
    ],
)
def test_discord_gateway_close_records_actionable_connection_health(
    provider_code: int,
    provider_reason: str,
    error_code: str,
    category: CommunicationErrorCategory,
    summary: str,
) -> None:
    connection = CommunicationConnection(
        organization_id=uuid4(),
        agent_id=uuid4(),
        platform_key="discord",
        display_name="Discord",
        credentials_encrypted="encrypted",
        driver_key_encrypted="encrypted",
    )
    connections = Mock()
    plugins = Mock()
    plugins.require.return_value = DiscordPlatformPlugin(cast(Any, SimpleNamespace(skip_discord_token_validation=True)))
    supervisor = PlatformIngressSupervisor(
        config=cast(Config, SimpleNamespace(agent_token_encryption_key="test-key")),
        connections=connections,
        gateway=Mock(),
        plugins=plugins,
    )
    identify_payloads: list[dict[str, Any]] = []

    async def gateway(socket: ServerConnection) -> None:
        await socket.send(json.dumps({"op": 10, "d": {"heartbeat_interval": 45_000}}))
        identify_payloads.append(json.loads(await socket.recv()))
        await socket.close(code=provider_code, reason=provider_reason)

    async def exercise() -> None:
        async with serve(gateway, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            with (
                patch(
                    "api.domains.communications.plugins.discord.DiscordClient.get_gateway_url",
                    return_value=f"ws://127.0.0.1:{port}",
                ),
                patch(
                    "api.domains.communications.supervisor.decrypt_token",
                    return_value=json.dumps({"bot_token": "test-token"}),
                ),
            ):
                task = asyncio.create_task(supervisor._maintain(connection))
                for _ in range(100):
                    if any(
                        call.args[1] == ConnectionObservedStatus.ERROR
                        for call in connections.record_health.call_args_list
                    ):
                        break
                    await asyncio.sleep(0.01)
                else:
                    pytest.fail("supervisor did not record the Discord gateway failure")
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

    asyncio.run(exercise())

    assert_that(identify_payloads[0]["op"], equal_to(2))
    error_call = next(
        call for call in connections.record_health.call_args_list if call.args[1] == ConnectionObservedStatus.ERROR
    )
    assert_that(error_call.kwargs["error_code"], equal_to(error_code))
    assert_that(error_call.kwargs["error_message"], equal_to(summary))
    assert_that(
        error_call.kwargs["error_details"],
        has_properties(
            category=equal_to(category),
            provider_code=equal_to(str(provider_code)),
            retryable=is_(False),
        ),
    )
    assert_that(str(error_call.kwargs["error_details"]), not_(contains_string(provider_reason)))


def test_health_events_are_debounced_to_failure_state_boundaries() -> None:
    # repeated retries and intermediate timing belong in the journal
    # and metrics — not one Domain Event per status change.
    emits = _emits_health_event
    # First failure from a healthy/stable state is event-worthy.
    assert_that(emits(ConnectionObservedStatus.PENDING, ConnectionObservedStatus.ERROR), equal_to(True))
    assert_that(emits(ConnectionObservedStatus.CONNECTED, ConnectionObservedStatus.ERROR), equal_to(True))
    # Retry churn inside a failure episode is not.
    assert_that(emits(ConnectionObservedStatus.ERROR, ConnectionObservedStatus.CONNECTING), equal_to(False))
    assert_that(emits(ConnectionObservedStatus.CONNECTING, ConnectionObservedStatus.ERROR), equal_to(False))
    assert_that(emits(ConnectionObservedStatus.ERROR, ConnectionObservedStatus.DEGRADED), equal_to(False))
    # Recovery is event-worthy.
    assert_that(emits(ConnectionObservedStatus.ERROR, ConnectionObservedStatus.CONNECTED), equal_to(True))
    assert_that(emits(ConnectionObservedStatus.DEGRADED, ConnectionObservedStatus.CONNECTED), equal_to(True))
    # First-ever connect is event-worthy; later CONNECTING/CONNECTED churn is not.
    assert_that(emits(None, ConnectionObservedStatus.CONNECTED), equal_to(True))
    assert_that(emits(ConnectionObservedStatus.PENDING, ConnectionObservedStatus.CONNECTING), equal_to(False))
    assert_that(emits(ConnectionObservedStatus.CONNECTING, ConnectionObservedStatus.CONNECTED), equal_to(False))
    assert_that(emits(ConnectionObservedStatus.CONNECTED, ConnectionObservedStatus.CONNECTING), equal_to(False))


def test_ingress_failures_back_off_exponentially() -> None:
    connection = CommunicationConnection(
        organization_id=uuid4(),
        agent_id=uuid4(),
        platform_key="missing",
        display_name="Broken Connection",
        credentials_encrypted="invalid",
        driver_key_encrypted="invalid",
    )
    connections = Mock()
    plugins = Mock()
    plugins.require.side_effect = RuntimeError("provider unreachable")
    supervisor = PlatformIngressSupervisor(
        config=cast(Config, SimpleNamespace(agent_token_encryption_key="test-key")),
        connections=connections,
        gateway=Mock(),
        plugins=plugins,
    )

    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        # Record the requested backoff but only yield, so the tight retry loop
        # still lets the polling task below interleave.
        await real_sleep(0)

    asyncio_module = cast(Any, asyncio)
    asyncio_module.sleep = fake_sleep
    try:

        async def exercise() -> None:
            task = asyncio.create_task(supervisor._maintain(connection))
            while len([delay for delay in sleeps if delay > 0]) < 4:
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        asyncio.run(exercise())
    finally:
        asyncio_module.sleep = real_sleep

    assert_that([delay for delay in sleeps if delay > 0][:4], contains_exactly(1.0, 2.0, 4.0, 8.0))


def test_reconcile_failure_does_not_end_the_supervisor() -> None:
    connections = Mock()
    connections.list_enabled.side_effect = [RuntimeError("database is starting up"), []]
    supervisor = PlatformIngressSupervisor(
        config=cast(
            Config, SimpleNamespace(agent_token_encryption_key="test-key", communication_journal_retention_days=7)
        ),
        connections=connections,
        gateway=Mock(),
        plugins=Mock(),
    )
    stop = asyncio.Event()

    async def exercise() -> None:
        task = asyncio.create_task(supervisor.run(stop))
        # The first reconcile pass raises; the supervisor must survive it and
        # complete a second pass instead of dying and disabling all ingress.
        while connections.list_enabled.call_count < 2:
            await asyncio.sleep(0)
        stop.set()
        await asyncio.wait_for(task, timeout=1)

    asyncio.run(exercise())
    assert_that(connections.list_enabled.call_count, equal_to(2))
