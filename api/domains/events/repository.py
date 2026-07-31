from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.events.constants import SENSITIVE_TOKEN_PARTS
from api.domains.events.models import (
    DomainEventEnvelope,
    EventDelivery,
    EventDeliveryDeadLetterReason,
    EventDeliveryStatus,
    OutboxMessage,
)
from api.domains.events.registry import DomainEventRegistry
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

MAX_DELIVERY_ERROR_CHARS = 2048


@dataclass(frozen=True)
class PendingDeliveryStats:
    pending_count: int
    oldest_pending_age_seconds: float | None


def bound_delivery_error(error: BaseException | str | None) -> str | None:
    if error is None:
        return None
    message = str(error)
    normalized = message.lower().replace("-", "_")
    if any(part in normalized for part in SENSITIVE_TOKEN_PARTS):
        return "Event delivery error contained sensitive details and was redacted"
    if len(message) <= MAX_DELIVERY_ERROR_CHARS:
        return message
    return f"{message[: MAX_DELIVERY_ERROR_CHARS - 13]}...[truncated]"


@inject
@singleton
@dataclass
class OutboxMessageRepository:
    delegate: PostgresRepositoryDelegate

    def create(self, event: DomainEventEnvelope, registry: DomainEventRegistry) -> OutboxMessage:
        with Session(self.delegate.engine) as session:
            message = self.stage(session=session, event=event, registry=registry)
            session.commit()
            session.refresh(message)
            return message

    def stage(
        self,
        *,
        session: Session,
        event: DomainEventEnvelope,
        registry: DomainEventRegistry,
    ) -> OutboxMessage:
        message = self.build_message(event)
        session.add(message)
        session.flush()
        deliveries = self.build_deliveries(message, registry.handler_names_for(event.event_name, event.schema_version))
        session.add_all(deliveries)
        session.flush()
        return message

    def build_message(self, event: DomainEventEnvelope) -> OutboxMessage:
        return OutboxMessage(
            event_id=event.event_id,
            event_name=event.event_name,
            schema_version=event.schema_version,
            occurred_at=event.occurred_at,
            event_scope=event.event_scope,
            organization_id=event.organization_id,
            actor=event.actor.model_dump(mode="json"),
            subject=event.subject.model_dump(mode="json"),
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            payload=event.payload,
        )

    def build_deliveries(self, message: OutboxMessage, handler_names: tuple[str, ...]) -> list[EventDelivery]:
        return [
            EventDelivery(
                outbox_message_id=message.id,
                event_id=message.event_id,
                event_scope=message.event_scope,
                organization_id=message.organization_id,
                handler_name=handler_name,
            )
            for handler_name in handler_names
        ]

    def get_by_event_id(self, event_id: UUID) -> OutboxMessage | None:
        with Session(self.delegate.engine) as session:
            return session.exec(select(OutboxMessage).where(OutboxMessage.event_id == event_id)).one_or_none()

    def get_latest(self) -> OutboxMessage | None:
        with Session(self.delegate.engine) as session:
            return session.exec(select(OutboxMessage).order_by(col(OutboxMessage.created_at).desc())).first()

    def list_deliveries_for_event(self, event_id: UUID) -> list[EventDelivery]:
        with Session(self.delegate.engine) as session:
            return list(session.exec(select(EventDelivery).where(EventDelivery.event_id == event_id)))

    def get_delivery(self, delivery_id: UUID) -> EventDelivery | None:
        with Session(self.delegate.engine) as session:
            return session.get(EventDelivery, delivery_id)

    def mark_delivery_enqueued(self, delivery_id: UUID, *, enqueued_at: datetime | None = None) -> EventDelivery | None:
        enqueued_at = enqueued_at or datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            delivery = session.exec(
                select(EventDelivery)
                .where(EventDelivery.id == delivery_id)
                .where(
                    cast(Any, EventDelivery.status).not_in(
                        [EventDeliveryStatus.SUCCEEDED, EventDeliveryStatus.DEAD_LETTERED]
                    )
                )
                .with_for_update()
            ).one_or_none()
            if delivery is None:
                return None
            delivery.status = EventDeliveryStatus.ENQUEUED
            delivery.enqueued_at = enqueued_at
            delivery.dead_letter_reason = None
            delivery.completed_at = None
            session.add(delivery)
            session.commit()
            session.refresh(delivery)
            return delivery

    def claim_delivery(
        self,
        delivery_id: UUID,
        *,
        claimed_at: datetime | None = None,
        processing_stale_before: datetime | None = None,
    ) -> EventDelivery | None:
        claimed_at = claimed_at or datetime.now(UTC)
        status_column = cast(Any, EventDelivery.status)
        eligible_conditions = [status_column == EventDeliveryStatus.ENQUEUED]
        if processing_stale_before is not None:
            claimed_at_column = cast(Any, EventDelivery.claimed_at)
            eligible_conditions.append(
                sa.and_(
                    status_column == EventDeliveryStatus.PROCESSING,
                    claimed_at_column.is_not(None),
                    claimed_at_column <= processing_stale_before,
                )
            )
        with Session(self.delegate.engine) as session:
            delivery = session.exec(
                select(EventDelivery)
                .where(EventDelivery.id == delivery_id)
                .where(sa.or_(*eligible_conditions))
                .with_for_update()
            ).one_or_none()
            if delivery is None:
                return None
            delivery.status = EventDeliveryStatus.PROCESSING
            delivery.claimed_at = claimed_at
            delivery.attempt_count += 1
            delivery.dead_letter_reason = None
            delivery.completed_at = None
            session.add(delivery)
            session.commit()
            session.refresh(delivery)
            return delivery

    def mark_delivery_retryable_failure(
        self, delivery_id: UUID, error: BaseException | str, *, enqueued_at: datetime | None = None
    ) -> EventDelivery | None:
        enqueued_at = enqueued_at or datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            delivery = session.get(EventDelivery, delivery_id)
            if delivery is None:
                return None
            # Re-mark ENQUEUED (not PROCESSING) so claim_delivery can immediately reclaim
            # the row when Dramatiq's own backoff fires the retry, instead of waiting for
            # the PROCESSING-staleness window. enqueued_at is refreshed to now so the
            # reconciliation sweep's ENQUEUED-staleness check doesn't race that same retry.
            delivery.status = EventDeliveryStatus.ENQUEUED
            delivery.enqueued_at = enqueued_at
            delivery.last_error = bound_delivery_error(error)
            delivery.dead_letter_reason = None
            session.add(delivery)
            session.commit()
            session.refresh(delivery)
            return delivery

    def mark_delivery_succeeded(
        self, delivery_id: UUID, *, completed_at: datetime | None = None
    ) -> EventDelivery | None:
        completed_at = completed_at or datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            delivery = session.get(EventDelivery, delivery_id)
            if delivery is None:
                return None
            delivery.status = EventDeliveryStatus.SUCCEEDED
            delivery.last_error = None
            delivery.dead_letter_reason = None
            delivery.completed_at = completed_at
            session.add(delivery)
            session.commit()
            session.refresh(delivery)
            return delivery

    def mark_delivery_dead_lettered(
        self,
        delivery_id: UUID,
        *,
        reason: EventDeliveryDeadLetterReason,
        error: BaseException | str,
        completed_at: datetime | None = None,
    ) -> EventDelivery | None:
        completed_at = completed_at or datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            delivery = session.get(EventDelivery, delivery_id)
            if delivery is None:
                return None
            delivery.status = EventDeliveryStatus.DEAD_LETTERED
            delivery.dead_letter_reason = reason
            delivery.last_error = bound_delivery_error(error)
            delivery.completed_at = completed_at
            session.add(delivery)
            session.commit()
            session.refresh(delivery)
            return delivery

    def claim_reconciliation_candidates(
        self,
        *,
        pending_created_before: datetime,
        enqueued_before: datetime,
        processing_claimed_before: datetime,
        limit: int,
        skip_locked: bool = True,
        claimed_at: datetime | None = None,
    ) -> list[EventDelivery]:
        claimed_at = claimed_at or datetime.now(UTC)
        statement = (
            select(EventDelivery)
            .where(
                sa.or_(
                    sa.and_(
                        cast(Any, EventDelivery.status) == EventDeliveryStatus.PENDING,
                        cast(Any, EventDelivery.created_at) <= pending_created_before,
                    ),
                    sa.and_(
                        cast(Any, EventDelivery.status) == EventDeliveryStatus.ENQUEUED,
                        cast(Any, EventDelivery.enqueued_at).is_not(None),
                        cast(Any, EventDelivery.enqueued_at) <= enqueued_before,
                    ),
                    sa.and_(
                        cast(Any, EventDelivery.status) == EventDeliveryStatus.PROCESSING,
                        cast(Any, EventDelivery.claimed_at).is_not(None),
                        cast(Any, EventDelivery.claimed_at) <= processing_claimed_before,
                    ),
                )
            )
            .order_by(cast(Any, EventDelivery.created_at))
            .limit(limit)
            .with_for_update(skip_locked=skip_locked)
        )
        # Claiming (flip to ENQUEUED) happens in the same transaction as the row lock,
        # so a concurrent reconciliation run's SKIP LOCKED actually excludes these rows
        # instead of racing a later, separately-committed mark_delivery_enqueued call.
        with Session(self.delegate.engine) as session:
            deliveries = list(session.exec(statement))
            for delivery in deliveries:
                delivery.status = EventDeliveryStatus.ENQUEUED
                delivery.enqueued_at = claimed_at
                delivery.dead_letter_reason = None
                delivery.completed_at = None
                session.add(delivery)
            session.commit()
            for delivery in deliveries:
                session.refresh(delivery)
            return deliveries

    def count(self) -> int:
        return self.delegate.count(OutboxMessage)

    def delivery_count(self) -> int:
        return self.delegate.count(EventDelivery)

    def pending_delivery_stats(self) -> PendingDeliveryStats:
        status_column = cast(Any, EventDelivery.status)
        with Session(self.delegate.engine) as session:
            pending_count = session.exec(
                select(sa.func.count()).select_from(EventDelivery).where(status_column == EventDeliveryStatus.PENDING)
            ).one()
            oldest_created_at = session.exec(
                select(sa.func.min(EventDelivery.created_at)).where(status_column == EventDeliveryStatus.PENDING)
            ).one()
        oldest_pending_age_seconds = None
        if oldest_created_at is not None:
            oldest_pending_age_seconds = (datetime.now(UTC) - oldest_created_at).total_seconds()
        return PendingDeliveryStats(
            pending_count=pending_count,
            oldest_pending_age_seconds=oldest_pending_age_seconds,
        )
