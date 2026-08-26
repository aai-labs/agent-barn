"""Persistence helpers for Communication operational history and diagnostics."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median
from typing import Any
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.communications.models import (
    CommunicationDelivery,
    CommunicationDeliveryCounts,
    CommunicationDeliveryStatus,
    CommunicationJournalEntry,
    CommunicationJournalEntryRead,
    CommunicationJournalStage,
    CommunicationLatencyRead,
    CommunicationPipelineCounts,
    CommunicationPolicyDisposition,
)
from api.domains.events.catalog import EVENT_REGISTRY
from api.domains.events.models import (
    ActorIdentity,
    EventDelivery,
    SubjectIdentity,
)
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

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


@dataclass(frozen=True)
class CommunicationDiagnosticsSnapshot:
    pipeline: CommunicationPipelineCounts
    delivery_counts: CommunicationDeliveryCounts
    queue_depth: int
    oldest_queued_age_seconds: float | None
    latency: CommunicationLatencyRead
    recent_failures: list[CommunicationJournalEntryRead]
    latest_transitions: list[CommunicationJournalEntryRead]


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
        window_start: datetime,
        window_end: datetime,
    ) -> CommunicationDiagnosticsSnapshot:
        with Session(self.delegate.engine) as session:
            journal_rows = list(
                session.exec(
                    select(CommunicationJournalEntry)
                    .where(
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
                    select(CommunicationDelivery).where(
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
                    select(CommunicationDelivery).where(
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

        read_entries = [CommunicationJournalEntryRead.model_validate(entry) for entry in journal_rows]
        failures = [
            entry
            for entry in read_entries
            if entry.stage
            in {
                CommunicationJournalStage.DEAD_LETTERED,
                CommunicationJournalStage.CONNECTION_ERROR,
            }
            or entry.error_code is not None
        ][:20]
        return CommunicationDiagnosticsSnapshot(
            pipeline=pipeline,
            delivery_counts=delivery_counts,
            queue_depth=len(queued_deliveries),
            oldest_queued_age_seconds=oldest_age,
            latency=latency,
            recent_failures=failures,
            latest_transitions=read_entries[:50],
        )

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
        normalized = value.lower().replace("-", "_")
        if any(part in normalized for part in _SENSITIVE_PARTS):
            return "Provider error details were redacted"
        return " ".join(value.split())[:500]

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
