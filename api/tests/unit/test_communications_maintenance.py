import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch
from uuid import uuid4

from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.domains.communications.maintenance import CommunicationsMaintenance
from api.domains.communications.models import CommunicationConnection, ConnectionObservedStatus
from api.domains.communications.repository import _emits_health_event


def maintenance(connections=None, operations=None):
    repository = connections or Mock()
    if connections is None:
        repository.list_enabled_email_page.return_value = []
    journal = operations or Mock()
    if operations is None:
        journal.prune_journal.return_value = 0
    return CommunicationsMaintenance(
        config=Config(agent_token_encryption_key="test-key", communication_journal_retention_days=7),
        connections=repository,
        plugins=Mock(),
        operations=journal,
    )


def email_connection():
    return CommunicationConnection(
        organization_id=uuid4(),
        agent_id=uuid4(),
        platform_key="email",
        display_name="Email",
        credentials_encrypted="encrypted",
        driver_key_encrypted="unused",
    )


def test_email_health_checks_configuration_without_provider_session_or_lease():
    worker = maintenance()
    connection = email_connection()
    worker.connections.list_enabled_email_page.return_value = [connection]
    with patch("api.domains.communications.maintenance.decrypt_token", return_value="{}"):
        asyncio.run(worker._reconcile())
    worker.plugins.require.assert_called_once_with("email")
    worker.plugins.require.return_value.validate_configuration.assert_called_once_with(
        connection.settings,
        {},
        organization_id=connection.organization_id,
        agent_id=connection.agent_id,
    )
    worker.connections.record_health.assert_called_once_with(
        connection.id,
        ConnectionObservedStatus.CONNECTED,
        expected_revision=connection.revision,
        error_code=None,
        error_message=None,
        error_details=None,
    )
    worker.connections.claim_ingress_lease.assert_not_called()
    worker.plugins.require.return_value.run_ingress.assert_not_called()


def test_bad_email_configuration_does_not_prevent_later_connections():
    worker = maintenance()
    first, second = email_connection(), email_connection()
    worker.connections.list_enabled_email_page.return_value = [first, second]
    worker.plugins.require.return_value.validate_configuration.side_effect = [ValueError("not configured"), None]
    with patch("api.domains.communications.maintenance.decrypt_token", return_value="{}"):
        asyncio.run(worker._reconcile())
    calls = worker.connections.record_health.call_args_list
    assert calls[0].args == (first.id, ConnectionObservedStatus.ERROR)
    assert calls[0].kwargs["error_details"].operation == "email_configuration"
    assert calls[1].args == (second.id, ConnectionObservedStatus.CONNECTED)


def test_email_health_scan_advances_bounded_pages_then_wraps():
    worker = maintenance()
    batch = [email_connection() for _ in range(100)]
    worker.connections.list_enabled_email_page.side_effect = [batch, [], []]
    with patch("api.domains.communications.maintenance.decrypt_token", return_value="{}"):
        for _ in range(3):
            asyncio.run(worker._reconcile())
    calls = worker.connections.list_enabled_email_page.call_args_list
    assert [call.kwargs for call in calls] == [
        {"after_id": None, "limit": 100},
        {"after_id": batch[-1].id, "limit": 100},
        {"after_id": None, "limit": 100},
    ]


def test_journal_failure_retries_next_cycle_and_does_not_skip_email_health():
    worker = maintenance()
    worker.operations.prune_journal.side_effect = [RuntimeError("database starting"), 0]
    asyncio.run(worker._reconcile())
    asyncio.run(worker._reconcile())
    assert worker.operations.prune_journal.call_count == 2
    assert worker.connections.list_enabled_email_page.call_count == 2


def test_journal_backlog_is_batched_until_drained_then_waits_five_minutes():
    worker = maintenance()
    worker.operations.prune_journal.side_effect = [2500, 1]
    for _ in range(3):
        asyncio.run(worker._reconcile())
    assert worker.operations.prune_journal.call_count == 2
    worker.operations.prune_journal.assert_called_with(retention_days=7, batch_size=2500)
    assert worker._next_journal_prune_at > datetime.now(UTC) + timedelta(minutes=4)


def test_failed_cycle_retries_and_stop_interrupts_wait():
    worker = maintenance()
    stop = asyncio.Event()
    attempts = []

    async def reconcile():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("database starting")
        stop.set()

    async def immediate_wait(awaitable, *, timeout):
        awaitable.close()
        raise TimeoutError

    async def exercise():
        with (
            patch.object(worker, "_reconcile", side_effect=reconcile),
            patch(
                "api.domains.communications.maintenance.asyncio.wait_for",
                side_effect=immediate_wait,
            ),
        ):
            await worker.run(stop)

    asyncio.run(exercise())
    assert len(attempts) == 2


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
