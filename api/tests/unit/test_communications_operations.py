from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from hamcrest import assert_that, equal_to

from api.domains.communications.models import (
    CommunicationConnectionIncidentOutcome,
    CommunicationConnectionStateRead,
    CommunicationDeliveryCounts,
    CommunicationJournalEntry,
    CommunicationJournalStage,
    ConnectionObservedStatus,
)
from api.domains.communications.operations import CommunicationOperationalRepository


def test_safe_error_summary_keeps_only_known_operational_messages() -> None:
    assert_that(
        CommunicationOperationalRepository.safe_error_summary("Communication Connection is unavailable"),
        equal_to("Communication Connection is unavailable"),
    )


@pytest.mark.parametrize(
    "provider_error",
    [
        "Provider rejected the request with status 409",
        "message body: customer email and private response",
        "request trace value opaque-value",
    ],
)
def test_safe_error_summary_redacts_provider_details(provider_error: str) -> None:
    assert_that(
        CommunicationOperationalRepository.safe_error_summary(provider_error),
        equal_to("Provider error details were redacted"),
    )


def test_journal_read_redacts_legacy_error_values() -> None:
    entry = CommunicationJournalEntry(
        organization_id=uuid4(),
        agent_id=uuid4(),
        connection_id=uuid4(),
        occurred_at=datetime.now(UTC),
        stage=CommunicationJournalStage.CONNECTION_ERROR,
        error_code="authorization-token",
        error_summary="provider rejected a bearer token containing customer data",
    )

    projected = CommunicationOperationalRepository._journal_read(
        entry,
        direction=None,
        delivery_status=None,
        delivery=None,
    )

    assert_that(projected.error_code, equal_to("REDACTED"))
    assert_that(projected.error_summary, equal_to("Provider error details were redacted"))


def test_connection_history_groups_health_states_and_ignores_admission_rows() -> None:
    organization_id = uuid4()
    agent_id = uuid4()
    connection_id = uuid4()
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = datetime(2026, 1, 1, 1, tzinfo=UTC)

    def entry(
        stage: CommunicationJournalStage,
        occurred_at: datetime,
        *,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> CommunicationJournalEntry:
        return CommunicationJournalEntry(
            id=uuid4(),
            organization_id=organization_id,
            agent_id=agent_id,
            connection_id=connection_id,
            occurred_at=occurred_at,
            stage=stage,
            error_code=error_code,
            error_summary=error_summary,
        )

    history = CommunicationOperationalRepository._build_connection_history(
        [
            entry(CommunicationJournalStage.PROVIDER_OBSERVED, window_start + timedelta(minutes=5)),
            entry(CommunicationJournalStage.POLICY_ADMITTED, window_start + timedelta(minutes=6)),
            entry(CommunicationJournalStage.CONNECTION_CONNECTING, window_start + timedelta(minutes=10)),
            entry(CommunicationJournalStage.RECONNECT_REQUESTED, window_start + timedelta(minutes=10)),
            entry(CommunicationJournalStage.RECONNECT_REQUESTED, window_start + timedelta(minutes=25)),
            entry(CommunicationJournalStage.CONNECTION_CONNECTED, window_start + timedelta(minutes=30)),
            entry(
                CommunicationJournalStage.CONNECTION_ERROR,
                window_start + timedelta(minutes=45),
                error_code="provider_error",
                error_summary="Communication Connection is unavailable",
            ),
        ],
        previous_connection_entry=entry(
            CommunicationJournalStage.CONNECTION_CONNECTED,
            window_start - timedelta(hours=1),
        ),
        window_start=window_start,
        window_end=window_end,
    )

    assert_that(
        [state.status for state in history],
        equal_to(
            [
                ConnectionObservedStatus.ERROR,
                ConnectionObservedStatus.CONNECTED,
                ConnectionObservedStatus.CONNECTING,
                ConnectionObservedStatus.CONNECTED,
            ]
        ),
    )
    assert_that([state.duration_ms for state in history], equal_to([900_000.0, 900_000.0, 1_200_000.0, 600_000.0]))
    assert_that(history[0].ended_at, equal_to(None))
    assert_that(history[0].next_status, equal_to(None))
    assert_that(history[0].error_code, equal_to("provider_error"))
    assert_that(history[0].error_summary, equal_to("Communication Connection is unavailable"))
    assert_that(history[2].reconnect_count, equal_to(2))
    assert_that(history[3].next_status, equal_to(ConnectionObservedStatus.CONNECTING))


def test_connection_health_projects_attempts_and_outage_metrics() -> None:
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = window_start + timedelta(hours=1)

    def state(
        status: ConnectionObservedStatus,
        started_at: datetime,
        ended_at: datetime | None,
        next_status: ConnectionObservedStatus | None,
        duration_ms: float,
        *,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> CommunicationConnectionStateRead:
        return CommunicationConnectionStateRead(
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            next_status=next_status,
            duration_ms=duration_ms,
            error_code=error_code,
            error_summary=error_summary,
        )

    history = [
        state(
            ConnectionObservedStatus.CONNECTED,
            window_start + timedelta(minutes=23, seconds=13),
            None,
            None,
            2_207_000,
        ),
        state(
            ConnectionObservedStatus.CONNECTING,
            window_start + timedelta(minutes=23, seconds=1),
            window_start + timedelta(minutes=23, seconds=13),
            ConnectionObservedStatus.CONNECTED,
            12_000,
        ),
        state(
            ConnectionObservedStatus.ERROR,
            window_start + timedelta(minutes=20),
            window_start + timedelta(minutes=23, seconds=1),
            ConnectionObservedStatus.CONNECTING,
            181_000,
            error_code="timeout",
            error_summary="Communication Connection is unavailable",
        ),
        state(
            ConnectionObservedStatus.CONNECTING,
            window_start + timedelta(minutes=19, seconds=48),
            window_start + timedelta(minutes=20),
            ConnectionObservedStatus.ERROR,
            12_000,
        ),
        state(
            ConnectionObservedStatus.CONNECTED,
            window_start + timedelta(minutes=10, seconds=12),
            window_start + timedelta(minutes=19, seconds=48),
            ConnectionObservedStatus.CONNECTING,
            588_000,
        ),
        state(
            ConnectionObservedStatus.CONNECTING,
            window_start + timedelta(minutes=10),
            window_start + timedelta(minutes=10, seconds=12),
            ConnectionObservedStatus.CONNECTED,
            12_000,
        ),
        state(
            ConnectionObservedStatus.CONNECTED,
            window_start,
            window_start + timedelta(minutes=10),
            ConnectionObservedStatus.CONNECTING,
            600_000,
        ),
    ]

    incidents, reconnect_count, median_connect_time_ms, longest_outage_ms = (
        CommunicationOperationalRepository._build_connection_health(history, window_end=window_end)
    )

    assert_that(
        [incident.outcome for incident in incidents],
        equal_to(
            [
                CommunicationConnectionIncidentOutcome.RECONNECTED,
                CommunicationConnectionIncidentOutcome.FAILED,
                CommunicationConnectionIncidentOutcome.RECONNECTED,
            ]
        ),
    )
    assert_that(
        [incident.started_at for incident in incidents],
        equal_to(
            [
                window_start + timedelta(minutes=23, seconds=1),
                window_start + timedelta(minutes=19, seconds=48),
                window_start + timedelta(minutes=10),
            ]
        ),
    )
    assert_that(incidents[0].connect_time_ms, equal_to(12_000.0))
    assert_that(incidents[0].outage_ms, equal_to(193_000.0))
    assert_that(incidents[0].cause_code, equal_to("timeout"))
    assert_that(incidents[1].cause_summary, equal_to("Communication Connection is unavailable"))
    assert_that(reconnect_count, equal_to(3))
    assert_that(median_connect_time_ms, equal_to(12_000.0))
    assert_that(longest_outage_ms, equal_to(193_000.0))


def test_end_to_end_health_treats_in_flight_deliveries_as_healthy() -> None:
    # AF-273 review: pending/processing deliveries inside the reporting window
    # are normal traffic — a busy Connection must not sit at "degraded".
    counts = CommunicationDeliveryCounts(pending=3, processing=1, total=4)
    assert_that(
        CommunicationOperationalRepository.end_to_end_health(
            ConnectionObservedStatus.CONNECTED, counts, oldest_pending_delivery_age_seconds=12.0
        ),
        equal_to("healthy"),
    )


def test_end_to_end_health_degrades_only_once_queued_work_goes_stale() -> None:
    counts = CommunicationDeliveryCounts(pending=2, total=2)
    threshold = CommunicationOperationalRepository._STALE_PENDING_DELIVERY_SECONDS
    assert_that(
        CommunicationOperationalRepository.end_to_end_health(
            ConnectionObservedStatus.CONNECTED, counts, oldest_pending_delivery_age_seconds=threshold
        ),
        equal_to("degraded"),
    )


def test_end_to_end_health_unavailable_delivery_does_not_linger_as_degraded() -> None:
    # One UNAVAILABLE delivery (Agent stopped when a message arrived) must not
    # keep the Connection degraded for the rest of the window once the Agent is
    # running again.
    counts = CommunicationDeliveryCounts(unavailable=1, total=1)
    assert_that(
        CommunicationOperationalRepository.end_to_end_health(
            ConnectionObservedStatus.CONNECTED, counts, oldest_pending_delivery_age_seconds=None
        ),
        equal_to("healthy"),
    )


def test_end_to_end_health_still_degrades_on_provider_error_and_dead_letters() -> None:
    assert_that(
        CommunicationOperationalRepository.end_to_end_health(
            ConnectionObservedStatus.ERROR, CommunicationDeliveryCounts()
        ),
        equal_to("degraded"),
    )
    assert_that(
        CommunicationOperationalRepository.end_to_end_health(
            ConnectionObservedStatus.CONNECTED, CommunicationDeliveryCounts(dead_lettered=1, total=1)
        ),
        equal_to("degraded"),
    )
