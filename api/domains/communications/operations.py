"""Persistence helpers for Communication operational history and diagnostics."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryCounts,
    CommunicationDeliveryStatus,
    CommunicationDirection,
    CommunicationFailureRead,
    CommunicationJournalEntry,
    CommunicationJournalEntryRead,
    CommunicationJournalStage,
    CommunicationLatencyRead,
    CommunicationPipelineCounts,
    CommunicationPolicyDisposition,
    CommunicationTransitionRead,
    ConnectionObservedStatus,
)
from api.domains.events.catalog import EVENT_REGISTRY
from api.domains.events.models import (
    ActorIdentity,
    EventDelivery,
    SubjectIdentity,
)
from api.domains.events.repository import OutboxMessageRepository
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination

_SAFE_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")
_SENSITIVE_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "client_secret",
    "credential",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
)
_REDACTED_ERROR_SUMMARY = "Provider error details were redacted"
_RECENT_FAILURE_LIMIT = 10
_LATEST_TRANSITION_LIMIT = 50
_SAFE_ERROR_SUMMARIES = {
    "agent was not running when the message arrived": "Agent was not running when the message arrived",
    "communication connection is unavailable": "Communication Connection is unavailable",
    "communication connection was retired": "Communication Connection was retired",
    _REDACTED_ERROR_SUMMARY.casefold(): _REDACTED_ERROR_SUMMARY,
}


@dataclass(frozen=True)
class CommunicationDiagnosticsSnapshot:
    pipeline: CommunicationPipelineCounts
    delivery_counts: CommunicationDeliveryCounts
    queue_depth: int
    oldest_queued_age_seconds: float | None
    oldest_pending_delivery_age_seconds: float | None
    latency: CommunicationLatencyRead
    last_successful_connection_at: datetime | None
    current_error_age_seconds: float | None
    consecutive_failure_count: int
    delivery_success_rate: float | None
    recent_failures: list[CommunicationFailureRead]
    latest_transitions: list[CommunicationTransitionRead]


@dataclass(frozen=True)
class CommunicationMetricsSnapshot:
    """Database rows needed to refresh low-cardinality Communications metrics."""

    connection_statuses: list[tuple[ConnectionObservedStatus | str | None, int]]
    queued_deliveries: list[tuple[CommunicationDirection | str, int, datetime]]


@inject
@singleton
@dataclass
class CommunicationOperationalRepository:
    """Owns append-only Communication journal writes and read-side diagnostics.

    Domain state mutations pass their open SQLModel session to ``stage_journal``
    and ``stage_event``. That keeps a delivery/connection transition and its
    internal Domain Event in the same transaction. Provider admission records
    can use ``record_journal`` because they precede durable delivery creation.
    """

    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def get_metrics_snapshot(self) -> CommunicationMetricsSnapshot:
        """Read the aggregate rows used by the Communications Prometheus gauges."""
        with Session(self.delegate.engine) as session:
            connection_statuses = list(
                session.exec(
                    select(CommunicationConnection.observed_status, sa.func.count())
                    .where(
                        col(CommunicationConnection.retired_at).is_(None),
                        col(CommunicationConnection.enabled).is_(True),
                    )
                    .group_by(CommunicationConnection.observed_status)
                ).all()
            )
            queued_deliveries = list(
                session.exec(
                    select(
                        CommunicationDelivery.direction,
                        sa.func.count(),
                        sa.func.min(CommunicationDelivery.available_at),
                    )
                    .join(
                        CommunicationConnection,
                        col(CommunicationConnection.id) == col(CommunicationDelivery.connection_id),
                    )
                    .where(
                        col(CommunicationDelivery.status).in_(
                            [CommunicationDeliveryStatus.PENDING, CommunicationDeliveryStatus.PROCESSING]
                        ),
                        col(CommunicationConnection.enabled).is_(True),
                        col(CommunicationConnection.retired_at).is_(None),
                    )
                    .group_by(CommunicationDelivery.direction)
                ).all()
            )
        return CommunicationMetricsSnapshot(
            connection_statuses=connection_statuses,
            queued_deliveries=queued_deliveries,
        )

    def stage_journal(
        self,
        *,
        session: Session,
        organization_id: UUID,
        agent_id: UUID,
        connection_id: UUID,
        stage: CommunicationJournalStage,
        delivery_id: UUID | None = None,
        disposition: CommunicationPolicyDisposition | None = None,
        attempt_number: int = 0,
        occurred_at: datetime | None = None,
        duration_ms: float | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> CommunicationJournalEntry:
        occurred_at = occurred_at or datetime.now(UTC)
        if duration_ms is None:
            duration_ms = self._duration_from_previous(
                session,
                connection_id=connection_id,
                delivery_id=delivery_id,
                occurred_at=occurred_at,
            )
        entry = CommunicationJournalEntry(
            organization_id=organization_id,
            agent_id=agent_id,
            connection_id=connection_id,
            delivery_id=delivery_id,
            occurred_at=occurred_at,
            stage=stage,
            disposition=disposition,
            attempt_number=max(0, attempt_number),
            duration_ms=max(0.0, duration_ms) if duration_ms is not None else None,
            error_code=self.safe_error_code(error_code),
            error_summary=self.safe_error_summary(error_summary),
        )
        session.add(entry)
        session.flush()
        return entry

    def record_journal(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        connection_id: UUID,
        stage: CommunicationJournalStage,
        delivery_id: UUID | None = None,
        disposition: CommunicationPolicyDisposition | None = None,
        attempt_number: int = 0,
        occurred_at: datetime | None = None,
        duration_ms: float | None = None,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> CommunicationJournalEntry:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            entry = self.stage_journal(
                session=session,
                organization_id=organization_id,
                agent_id=agent_id,
                connection_id=connection_id,
                stage=stage,
                delivery_id=delivery_id,
                disposition=disposition,
                attempt_number=attempt_number,
                occurred_at=occurred_at,
                duration_ms=duration_ms,
                error_code=error_code,
                error_summary=error_summary,
            )
            session.commit()
            return entry

    def stage_event(
        self,
        *,
        session: Session,
        event_name: str,
        organization_id: UUID,
        actor: ActorIdentity,
        subject: SubjectIdentity,
        payload: dict[str, Any],
        occurred_at: datetime | None = None,
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
    ) -> list[UUID]:
        event = EVENT_REGISTRY.build_event(
            event_name=event_name,
            schema_version=1,
            occurred_at=occurred_at or datetime.now(UTC),
            organization_id=organization_id,
            actor=actor,
            subject=subject,
            correlation_id=correlation_id or uuid4(),
            causation_id=causation_id,
            payload=payload,
        )
        self.outbox_repository.stage(session=session, event=event, registry=EVENT_REGISTRY)
        return list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))

    def has_stage(
        self,
        session: Session,
        *,
        delivery_id: UUID,
        stage: CommunicationJournalStage,
    ) -> bool:
        return (
            session.exec(
                select(CommunicationJournalEntry.id)
                .where(
                    col(CommunicationJournalEntry.delivery_id) == delivery_id,
                    col(CommunicationJournalEntry.stage) == stage,
                )
                .limit(1)
            ).one_or_none()
            is not None
        )

    def diagnostics_snapshot(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        connection_id: UUID,
        authorization_scope: AuthorizationScope,
        window_start: datetime,
        window_end: datetime,
    ) -> CommunicationDiagnosticsSnapshot:
        with Session(self.delegate.engine) as session:
            agent_visibility = agent_scope_predicates(authorization_scope)
            journal_rows = list(
                session.exec(
                    select(CommunicationJournalEntry)
                    .join(Agent, col(Agent.id) == col(CommunicationJournalEntry.agent_id))
                    .where(
                        *agent_visibility,
                        col(CommunicationJournalEntry.organization_id) == organization_id,
                        col(CommunicationJournalEntry.agent_id) == agent_id,
                        col(CommunicationJournalEntry.connection_id) == connection_id,
                        col(CommunicationJournalEntry.occurred_at) >= window_start,
                        col(CommunicationJournalEntry.occurred_at) <= window_end,
                    )
                    .order_by(
                        col(CommunicationJournalEntry.occurred_at).desc(), col(CommunicationJournalEntry.id).desc()
                    )
                ).all()
            )
            deliveries = list(
                session.exec(
                    select(CommunicationDelivery)
                    .join(Agent, col(Agent.id) == col(CommunicationDelivery.agent_id))
                    .where(
                        *agent_visibility,
                        col(CommunicationDelivery.organization_id) == organization_id,
                        col(CommunicationDelivery.agent_id) == agent_id,
                        col(CommunicationDelivery.connection_id) == connection_id,
                        col(CommunicationDelivery.created_at) <= window_end,
                        col(CommunicationDelivery.created_at) >= window_start,
                    )
                ).all()
            )
            queued_deliveries = list(
                session.exec(
                    select(CommunicationDelivery)
                    .join(Agent, col(Agent.id) == col(CommunicationDelivery.agent_id))
                    .where(
                        *agent_visibility,
                        col(CommunicationDelivery.organization_id) == organization_id,
                        col(CommunicationDelivery.agent_id) == agent_id,
                        col(CommunicationDelivery.connection_id) == connection_id,
                        col(CommunicationDelivery.status).in_(
                            [CommunicationDeliveryStatus.PENDING, CommunicationDeliveryStatus.PROCESSING]
                        ),
                        col(CommunicationDelivery.created_at) <= window_end,
                    )
                ).all()
            )
            # These three reads are deliberately unbounded by the diagnostics
            # window: they answer "what is this Connection's current health
            # trajectory", not "what happened in the selected window".
            last_connected_at = session.exec(
                select(CommunicationJournalEntry.occurred_at)
                .join(Agent, col(Agent.id) == col(CommunicationJournalEntry.agent_id))
                .where(
                    *agent_visibility,
                    col(CommunicationJournalEntry.organization_id) == organization_id,
                    col(CommunicationJournalEntry.agent_id) == agent_id,
                    col(CommunicationJournalEntry.connection_id) == connection_id,
                    col(CommunicationJournalEntry.stage) == CommunicationJournalStage.CONNECTION_CONNECTED,
                )
                .order_by(col(CommunicationJournalEntry.occurred_at).desc())
                .limit(1)
            ).first()
            latest_connectivity_entry = session.exec(
                select(CommunicationJournalEntry.stage, CommunicationJournalEntry.occurred_at)
                .join(Agent, col(Agent.id) == col(CommunicationJournalEntry.agent_id))
                .where(
                    *agent_visibility,
                    col(CommunicationJournalEntry.organization_id) == organization_id,
                    col(CommunicationJournalEntry.agent_id) == agent_id,
                    col(CommunicationJournalEntry.connection_id) == connection_id,
                    col(CommunicationJournalEntry.stage).in_(
                        [CommunicationJournalStage.CONNECTION_CONNECTED, CommunicationJournalStage.CONNECTION_ERROR]
                    ),
                )
                .order_by(col(CommunicationJournalEntry.occurred_at).desc())
                .limit(1)
            ).first()
            recent_delivery_statuses = list(
                session.exec(
                    select(CommunicationDelivery.status)
                    .join(Agent, col(Agent.id) == col(CommunicationDelivery.agent_id))
                    .where(
                        *agent_visibility,
                        col(CommunicationDelivery.organization_id) == organization_id,
                        col(CommunicationDelivery.agent_id) == agent_id,
                        col(CommunicationDelivery.connection_id) == connection_id,
                    )
                    .order_by(col(CommunicationDelivery.created_at).desc())
                    .limit(200)
                ).all()
            )

        pipeline_values = {stage.value: 0 for stage in CommunicationJournalStage}
        for entry in journal_rows:
            stage = self._enum_value(entry.stage)
            pipeline_values[stage] = pipeline_values.get(stage, 0) + 1
        pipeline = CommunicationPipelineCounts(
            provider_observed=pipeline_values.get(CommunicationJournalStage.PROVIDER_OBSERVED.value, 0),
            policy_admitted=pipeline_values.get(CommunicationJournalStage.POLICY_ADMITTED.value, 0),
            queued=pipeline_values.get(CommunicationJournalStage.QUEUED.value, 0),
            agent_claimed=pipeline_values.get(CommunicationJournalStage.AGENT_CLAIMED.value, 0),
            model_completed=pipeline_values.get(CommunicationJournalStage.MODEL_COMPLETED.value, 0),
            reply_queued=pipeline_values.get(CommunicationJournalStage.REPLY_QUEUED.value, 0),
            provider_delivered=pipeline_values.get(CommunicationJournalStage.PROVIDER_DELIVERED.value, 0),
            dead_lettered=pipeline_values.get(CommunicationJournalStage.DEAD_LETTERED.value, 0),
        )

        status_counts: dict[str, int] = {status.value.lower(): 0 for status in CommunicationDeliveryStatus}
        for delivery in deliveries:
            status = self._enum_value(delivery.status)
            status_counts[status.lower()] = status_counts.get(status.lower(), 0) + 1
        delivery_counts = CommunicationDeliveryCounts(
            total=len(deliveries),
            pending=status_counts.get("pending", 0),
            processing=status_counts.get("processing", 0),
            succeeded=status_counts.get("succeeded", 0),
            dead_lettered=status_counts.get("dead_lettered", 0),
            cancelled=status_counts.get("cancelled", 0),
            unavailable=status_counts.get("unavailable", 0),
        )

        now = datetime.now(UTC)
        oldest = min((delivery.available_at for delivery in queued_deliveries), default=None)
        oldest_age = max(0.0, (now - oldest).total_seconds()) if oldest is not None else None
        oldest_pending = min(
            (
                delivery.available_at
                for delivery in queued_deliveries
                if self._enum_value(delivery.status) == CommunicationDeliveryStatus.PENDING.value
            ),
            default=None,
        )
        oldest_pending_age = max(0.0, (now - oldest_pending).total_seconds()) if oldest_pending is not None else None

        current_error_age: float | None = None
        if latest_connectivity_entry is not None:
            latest_stage, latest_occurred_at = latest_connectivity_entry
            if self._enum_value(latest_stage) == CommunicationJournalStage.CONNECTION_ERROR.value:
                current_error_age = max(0.0, (now - latest_occurred_at).total_seconds())

        consecutive_failure_count = 0
        for delivery_status in recent_delivery_statuses:
            status_value = self._enum_value(delivery_status)
            if status_value in {
                CommunicationDeliveryStatus.PENDING.value,
                CommunicationDeliveryStatus.PROCESSING.value,
            }:
                continue
            if status_value in {
                CommunicationDeliveryStatus.DEAD_LETTERED.value,
                CommunicationDeliveryStatus.UNAVAILABLE.value,
            }:
                consecutive_failure_count += 1
                continue
            break

        latency_samples: list[tuple[datetime, float]] = []
        for delivery in deliveries:
            if (
                delivery.completed_at is not None
                and delivery.claimed_at is not None
                and self._enum_value(delivery.status) in {"SUCCEEDED", "DEAD_LETTERED"}
            ):
                latency_samples.append(
                    (
                        delivery.completed_at,
                        max(0.0, (delivery.completed_at - delivery.claimed_at).total_seconds() * 1000),
                    )
                )
        latency_samples.sort(key=lambda sample: sample[0])
        latencies = [sample[1] for sample in latency_samples]
        latency = CommunicationLatencyRead(
            sample_count=len(latencies),
            average_ms=sum(latencies) / len(latencies) if latencies else None,
            p50_ms=float(median(latencies)) if latencies else None,
            latest_ms=latencies[-1] if latencies else None,
        )

        terminal_deliveries = (
            delivery_counts.succeeded
            + delivery_counts.dead_lettered
            + delivery_counts.cancelled
            + delivery_counts.unavailable
        )
        delivery_success_rate = delivery_counts.succeeded / terminal_deliveries if terminal_deliveries else None

        recent_failures = [
            CommunicationFailureRead(
                occurred_at=entry.occurred_at,
                stage=CommunicationJournalStage(self._enum_value(entry.stage)),
                delivery_id=entry.delivery_id,
                error_code=self.safe_error_code(entry.error_code),
                error_summary=self.safe_error_summary(entry.error_summary),
            )
            for entry in journal_rows
            if entry.error_code is not None
            or self._enum_value(entry.stage)
            in {
                CommunicationJournalStage.CONNECTION_ERROR.value,
                CommunicationJournalStage.DEAD_LETTERED.value,
            }
        ][:_RECENT_FAILURE_LIMIT]
        latest_transitions = [
            CommunicationTransitionRead(
                occurred_at=entry.occurred_at,
                stage=CommunicationJournalStage(self._enum_value(entry.stage)),
                delivery_id=entry.delivery_id,
                disposition=(
                    CommunicationPolicyDisposition(self._enum_value(entry.disposition))
                    if entry.disposition is not None
                    else None
                ),
                attempt_number=entry.attempt_number,
                duration_ms=entry.duration_ms,
            )
            for entry in journal_rows[:_LATEST_TRANSITION_LIMIT]
        ]

        return CommunicationDiagnosticsSnapshot(
            pipeline=pipeline,
            delivery_counts=delivery_counts,
            queue_depth=len(queued_deliveries),
            oldest_queued_age_seconds=oldest_age,
            oldest_pending_delivery_age_seconds=oldest_pending_age,
            latency=latency,
            last_successful_connection_at=last_connected_at,
            current_error_age_seconds=current_error_age,
            consecutive_failure_count=consecutive_failure_count,
            delivery_success_rate=delivery_success_rate,
            recent_failures=recent_failures,
            latest_transitions=latest_transitions,
        )

    def find_journal_page(
        self,
        *,
        organization_id: UUID,
        agent_id: UUID,
        connection_id: UUID,
        authorization_scope: AuthorizationScope,
        pagination: Pagination,
        kind: str,
        since: datetime | None = None,
        until: datetime | None = None,
        stage: CommunicationJournalStage | None = None,
        failed_only: bool = False,
        retryable_only: bool = False,
        direction: CommunicationDirection | None = None,
        delivery_id: UUID | None = None,
        order: str = "desc",
    ) -> PaginatedItems[CommunicationJournalEntryRead]:
        """Return the Connection's content-free operational history.

        Newest first by default. ``delivery_id`` with ``order="asc"`` gives a
        single Delivery's lifecycle in chronological order, which is how the
        per-delivery drill-down is served without a separate read model.
        """
        with Session(self.delegate.engine) as session:
            agent_visibility = agent_scope_predicates(authorization_scope)
            predicates = [
                *agent_visibility,
                col(CommunicationJournalEntry.organization_id) == organization_id,
                col(CommunicationJournalEntry.agent_id) == agent_id,
                col(CommunicationJournalEntry.connection_id) == connection_id,
            ]
            if kind == "delivery":
                predicates.append(col(CommunicationJournalEntry.delivery_id).is_not(None))
            elif kind == "connection":
                predicates.append(col(CommunicationJournalEntry.delivery_id).is_(None))
            if delivery_id is not None:
                predicates.append(col(CommunicationJournalEntry.delivery_id) == delivery_id)
            if since is not None:
                predicates.append(col(CommunicationJournalEntry.occurred_at) >= since)
            if until is not None:
                predicates.append(col(CommunicationJournalEntry.occurred_at) <= until)
            if stage is not None:
                predicates.append(col(CommunicationJournalEntry.stage) == stage)
            if failed_only:
                predicates.append(col(CommunicationJournalEntry.error_code).is_not(None))
            if retryable_only:
                predicates.append(col(CommunicationJournalEntry.stage) == CommunicationJournalStage.DEAD_LETTERED)
                predicates.append(col(CommunicationDelivery.status) == CommunicationDeliveryStatus.DEAD_LETTERED)
                predicates.append(col(CommunicationDelivery.direction) == CommunicationDirection.OUTBOUND)
            if direction is not None:
                predicates.append(col(CommunicationDelivery.direction) == direction)

            total = session.exec(
                select(sa.func.count())
                .select_from(CommunicationJournalEntry)
                .join(Agent, col(Agent.id) == col(CommunicationJournalEntry.agent_id))
                .outerjoin(
                    CommunicationDelivery,
                    col(CommunicationDelivery.id) == col(CommunicationJournalEntry.delivery_id),
                )
                .where(*predicates)
            ).one()
            occurred_order = (
                col(CommunicationJournalEntry.occurred_at).asc()
                if order == "asc"
                else col(CommunicationJournalEntry.occurred_at).desc()
            )
            id_order = (
                col(CommunicationJournalEntry.id).asc() if order == "asc" else col(CommunicationJournalEntry.id).desc()
            )
            rows = list(
                session.exec(
                    select(
                        CommunicationJournalEntry,
                        CommunicationDelivery.direction,
                        CommunicationDelivery.status,
                        CommunicationDelivery,
                    )
                    .join(Agent, col(Agent.id) == col(CommunicationJournalEntry.agent_id))
                    .outerjoin(
                        CommunicationDelivery,
                        col(CommunicationDelivery.id) == col(CommunicationJournalEntry.delivery_id),
                    )
                    .where(*predicates)
                    .order_by(occurred_order, id_order)
                    .offset((pagination.page - 1) * pagination.size)
                    .limit(pagination.size)
                ).all()
            )
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=[
                self._journal_read(
                    entry,
                    direction=direction,
                    delivery_status=delivery_status,
                    delivery=delivery,
                )
                for entry, direction, delivery_status, delivery in rows
            ],
        )

    @staticmethod
    def _journal_read(
        entry: CommunicationJournalEntry,
        *,
        direction: CommunicationDirection | str | None,
        delivery_status: CommunicationDeliveryStatus | str | None,
        delivery: CommunicationDelivery | None,
    ) -> CommunicationJournalEntryRead:
        """Project a journal row without re-exposing legacy unsafe error text."""
        values = CommunicationJournalEntryRead.model_validate(entry).model_dump()
        values.update(
            {
                "error_code": CommunicationOperationalRepository.safe_error_code(entry.error_code),
                "error_summary": CommunicationOperationalRepository.safe_error_summary(entry.error_summary),
                "direction": direction,
                "delivery_status": delivery_status,
                **CommunicationOperationalRepository._delivery_journal_details(delivery),
            }
        )
        return CommunicationJournalEntryRead.model_validate(values)

    @staticmethod
    def _delivery_journal_details(delivery: CommunicationDelivery | None) -> dict[str, float | datetime | None]:
        """Return safe, current operational timing for a Delivery-backed Journal row."""
        if delivery is None:
            return {"queue_wait_ms": None, "processing_ms": None, "next_retry_at": None}

        queue_wait_ms = None
        if delivery.claimed_at is not None:
            queue_wait_ms = max(0.0, (delivery.claimed_at - delivery.available_at).total_seconds() * 1000)

        processing_ms = None
        if delivery.claimed_at is not None and delivery.completed_at is not None:
            processing_ms = max(0.0, (delivery.completed_at - delivery.claimed_at).total_seconds() * 1000)

        next_retry_at = None
        if (
            CommunicationOperationalRepository._enum_value(delivery.status) == CommunicationDeliveryStatus.PENDING.value
            and delivery.attempt_count > 0
        ):
            next_retry_at = delivery.available_at

        return {
            "queue_wait_ms": queue_wait_ms,
            "processing_ms": processing_ms,
            "next_retry_at": next_retry_at,
        }

    @staticmethod
    def end_to_end_health(
        provider_status: Any,
        delivery_counts: CommunicationDeliveryCounts,
    ) -> str:
        provider_value = getattr(provider_status, "value", provider_status)
        if delivery_counts.dead_lettered or delivery_counts.unavailable:
            return "degraded"
        if provider_value in {"ERROR", "DEGRADED"}:
            return "degraded"
        if delivery_counts.pending or delivery_counts.processing:
            return "degraded"
        if provider_value == "CONNECTED" and delivery_counts.total:
            return "healthy"
        if provider_value == "CONNECTED":
            return "no_data"
        return "unavailable"

    @staticmethod
    def safe_error_code(value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.lower().replace("-", "_")
        if any(part in normalized for part in _SENSITIVE_PARTS) or not _SAFE_CODE.fullmatch(value):
            return "REDACTED"
        return value

    @staticmethod
    def safe_error_summary(value: str | None) -> str | None:
        if not value:
            return None
        normalized = " ".join(value.split())
        return _SAFE_ERROR_SUMMARIES.get(normalized.casefold(), _REDACTED_ERROR_SUMMARY)

    def prune_journal(self, *, retention_days: int) -> int:
        """Delete journal rows older than the configured bounded retention window."""
        if retention_days < 1:
            raise ValueError("Communication journal retention must be at least one day")
        cutoff = datetime.now(UTC) - timedelta(days=retention_days)
        with Session(self.delegate.engine) as session:
            result = session.exec(
                sa.delete(CommunicationJournalEntry).where(
                    col(CommunicationJournalEntry.occurred_at) < cutoff,
                )
            )
            session.commit()
            return int(result.rowcount or 0)

    @staticmethod
    def _enum_value(value: Any) -> str:
        return str(getattr(value, "value", value))

    @staticmethod
    def _duration_from_previous(
        session: Session,
        *,
        connection_id: UUID,
        delivery_id: UUID | None,
        occurred_at: datetime,
    ) -> float | None:
        predicates = [col(CommunicationJournalEntry.connection_id) == connection_id]
        if delivery_id is not None:
            predicates.append(col(CommunicationJournalEntry.delivery_id) == delivery_id)
        else:
            predicates.append(col(CommunicationJournalEntry.delivery_id).is_(None))
        previous = session.exec(
            select(CommunicationJournalEntry.occurred_at)
            .where(*predicates, col(CommunicationJournalEntry.occurred_at) <= occurred_at)
            .order_by(col(CommunicationJournalEntry.occurred_at).desc())
            .limit(1)
        ).first()
        if previous is None:
            return None
        return (occurred_at - previous).total_seconds() * 1000
