import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
from hamcrest import assert_that, contains_exactly, equal_to

from api.core.config import Config
from api.domains.communications.models import (
    CommunicationConnection,
    ConnectionObservedStatus,
)
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


def test_reconcile_does_not_lease_a_connection_without_supervised_ingress() -> None:
    connection = CommunicationConnection(
        organization_id=uuid4(),
        agent_id=uuid4(),
        platform_key="web",
        display_name="Web Chat",
        credentials_encrypted="unused",
        driver_key_encrypted="unused",
    )
    connections = Mock()
    connections.list_enabled.return_value = [connection]
    plugins = Mock()
    plugins.require.return_value = SimpleNamespace(capabilities=frozenset())
    supervisor = PlatformIngressSupervisor(
        config=cast(Config, SimpleNamespace(agent_token_encryption_key="test-key")),
        connections=connections,
        gateway=Mock(),
        plugins=plugins,
    )
    tasks: dict = {}

    asyncio.run(supervisor._reconcile(tasks))

    assert tasks == {}
    connections.claim_ingress_lease.assert_not_called()
    plugins.require.assert_called_once_with("web")
