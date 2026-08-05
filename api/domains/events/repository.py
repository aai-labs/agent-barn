from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, or_, select

from api.domains.events.constants import (
    EVENT_DELIVERY_PROCESSING_STALE_SECONDS,
    EVENT_DELIVERY_RECONCILIATION_ENQUEUED_STALE_SECONDS,
    EVENT_DELIVERY_RECONCILIATION_PENDING_GRACE_SECONDS,
    SENSITIVE_TOKEN_PARTS,
)
from api.domains.events.models import (
    DomainEventEnvelope,
    EventDelivery,
    EventDeliveryActiveStateStats,
    EventDeliveryDeadLetterReason,
    EventDeliveryFilter,
    EventDeliveryRead,
    EventDeliverySortDirection,
    EventDeliveryStatus,
    EventDeliveryStatusCounts,
    EventDeliverySummaryRead,
    OutboxMessage,
)
from api.domains.events.registry import DomainEventRegistry
from api.domains.organizations.models import Organization
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination

MAX_DELIVERY_ERROR_CHARS = 2048

_STATUS_SINCE_CLOCK: dict[EventDeliveryStatus, str] = {
    EventDeliveryStatus.PENDING: "created_at",
    EventDeliveryStatus.ENQUEUED: "enqueued_at",
    EventDeliveryStatus.PROCESSING: "claimed_at",
    EventDeliveryStatus.SUCCEEDED: "completed_at",
    EventDeliveryStatus.DEAD_LETTERED: "completed_at",
}


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

    def _active_state_stats(
        self,
        session: Session,
        *,
        status: EventDeliveryStatus,
        clock_column: Any,
        now: datetime,
        stale_seconds: int,
    ) -> EventDeliveryActiveStateStats:
        threshold = now - timedelta(seconds=stale_seconds)
        status_column = cast(Any, EventDelivery.status)
        count, oldest_clock, stale_count, unknown_age_count = session.exec(
            select(
                sa.func.count(),
                sa.func.min(clock_column),
                sa.func.count().filter(clock_column.is_not(None), clock_column <= threshold),
                sa.func.count().filter(clock_column.is_(None)),
            ).where(status_column == status)
        ).one()
        oldest_age_seconds = (now - oldest_clock).total_seconds() if oldest_clock is not None else None
        return EventDeliveryActiveStateStats(
            count=count,
            oldest_age_seconds=oldest_age_seconds,
            stale_threshold_seconds=stale_seconds,
            stale_count=stale_count,
            unknown_age_count=unknown_age_count,
        )

    def get_delivery_summary(self) -> EventDeliverySummaryRead:
        now = datetime.now(UTC)
        status_column = cast(Any, EventDelivery.status)
        with Session(self.delegate.engine) as session:
            rows = session.exec(select(status_column, sa.func.count()).group_by(status_column)).all()
            counts = {status: 0 for status in EventDeliveryStatus}
            for status, count in rows:
                counts[EventDeliveryStatus(status)] = count

            pending = self._active_state_stats(
                session,
                status=EventDeliveryStatus.PENDING,
                clock_column=cast(Any, EventDelivery.created_at),
                now=now,
                stale_seconds=EVENT_DELIVERY_RECONCILIATION_PENDING_GRACE_SECONDS,
            )
            enqueued = self._active_state_stats(
                session,
                status=EventDeliveryStatus.ENQUEUED,
                clock_column=cast(Any, EventDelivery.enqueued_at),
                now=now,
                stale_seconds=EVENT_DELIVERY_RECONCILIATION_ENQUEUED_STALE_SECONDS,
            )
            processing = self._active_state_stats(
                session,
                status=EventDeliveryStatus.PROCESSING,
                clock_column=cast(Any, EventDelivery.claimed_at),
                now=now,
                stale_seconds=EVENT_DELIVERY_PROCESSING_STALE_SECONDS,
            )

        return EventDeliverySummaryRead(
            observed_at=now,
            total_count=sum(counts.values()),
            status_counts=EventDeliveryStatusCounts(
                pending=counts[EventDeliveryStatus.PENDING],
                enqueued=counts[EventDeliveryStatus.ENQUEUED],
                processing=counts[EventDeliveryStatus.PROCESSING],
                succeeded=counts[EventDeliveryStatus.SUCCEEDED],
                dead_lettered=counts[EventDeliveryStatus.DEAD_LETTERED],
            ),
            pending=pending,
            enqueued=enqueued,
            processing=processing,
        )

    @staticmethod
    def _ilike_prefix(column: Any, term: str) -> Any:
        # Escape LIKE wildcards in user input so `_`/`%` are matched literally rather
        # than as pattern metacharacters.
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return col(column).ilike(f"{escaped}%", escape="\\")

    @staticmethod
    def _delivery_explorer_joins(query):
        # Shared join chain for the explorer row and count queries so the
        # OutboxMessage/Organization wiring lives in exactly one place.
        return query.join(OutboxMessage, col(OutboxMessage.id) == col(EventDelivery.outbox_message_id)).outerjoin(
            Organization, col(Organization.id) == col(EventDelivery.organization_id)
        )

    def _build_delivery_explorer_query(self):
        event_name_col = col(OutboxMessage.event_name).label("event_name")
        schema_version_col = col(OutboxMessage.schema_version).label("schema_version")
        organization_name_col = col(Organization.name).label("organization_name")
        return self._delivery_explorer_joins(
            select(EventDelivery, event_name_col, schema_version_col, organization_name_col)
        )

    def _apply_delivery_explorer_filters(self, query, delivery_filter: EventDeliveryFilter):
        if delivery_filter.status is not None:
            query = query.where(cast(Any, EventDelivery.status) == delivery_filter.status)
        if delivery_filter.organization_id is not None:
            query = query.where(col(EventDelivery.organization_id) == delivery_filter.organization_id)
        if delivery_filter.event_name is not None:
            query = query.where(col(OutboxMessage.event_name) == delivery_filter.event_name)
        if delivery_filter.created_from is not None:
            query = query.where(col(EventDelivery.created_at) >= delivery_filter.created_from)
        if delivery_filter.created_to is not None:
            query = query.where(col(EventDelivery.created_at) <= delivery_filter.created_to)

        search = delivery_filter.search.strip() if delivery_filter.search else None
        if search:
            conditions = [
                self._ilike_prefix(Organization.name, search),
                self._ilike_prefix(OutboxMessage.event_name, search),
                self._ilike_prefix(EventDelivery.handler_name, search),
            ]
            try:
                search_uuid = UUID(search)
            except ValueError:
                search_uuid = None
            if search_uuid is not None:
                conditions.append(col(EventDelivery.id) == search_uuid)
                conditions.append(col(EventDelivery.event_id) == search_uuid)
            query = query.where(or_(*conditions))

        return query

    @staticmethod
    def _status_since(delivery: EventDelivery) -> datetime | None:
        clock_field = _STATUS_SINCE_CLOCK[delivery.status]
        return getattr(delivery, clock_field)

    def _to_delivery_read(
        self,
        delivery: EventDelivery,
        *,
        event_name: str,
        schema_version: int,
        organization_name: str | None,
        observed_at: datetime,
    ) -> EventDeliveryRead:
        return EventDeliveryRead(
            id=delivery.id,
            event_id=delivery.event_id,
            event_name=event_name,
            schema_version=schema_version,
            handler_name=delivery.handler_name,
            organization_id=delivery.organization_id,
            organization_name=organization_name,
            status=delivery.status,
            attempt_count=delivery.attempt_count,
            dead_letter_reason=delivery.dead_letter_reason,
            last_error=bound_delivery_error(delivery.last_error),
            created_at=delivery.created_at,
            enqueued_at=delivery.enqueued_at,
            claimed_at=delivery.claimed_at,
            completed_at=delivery.completed_at,
            status_since=self._status_since(delivery),
            observed_at=observed_at,
        )

    def find_delivery_explorer_page(
        self,
        *,
        delivery_filter: EventDeliveryFilter,
        pagination: Pagination,
    ) -> PaginatedItems[EventDeliveryRead]:
        observed_at = datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            query = self._apply_delivery_explorer_filters(self._build_delivery_explorer_query(), delivery_filter)

            created_at_col = cast(Any, EventDelivery.created_at)
            id_col = cast(Any, EventDelivery.id)
            if delivery_filter.sort == EventDeliverySortDirection.OLDEST_FIRST:
                query = query.order_by(created_at_col.asc(), id_col.asc())
            else:
                query = query.order_by(created_at_col.desc(), id_col.desc())

            count_query = self._apply_delivery_explorer_filters(
                self._delivery_explorer_joins(select(sa.func.count()).select_from(EventDelivery)),
                delivery_filter,
            )
            total = session.scalar(count_query) or 0

            query = query.offset((pagination.page - 1) * pagination.size).limit(pagination.size)
            rows = session.exec(query).all()
            items = [
                self._to_delivery_read(
                    delivery,
                    event_name=event_name,
                    schema_version=schema_version,
                    organization_name=organization_name,
                    observed_at=observed_at,
                )
                for delivery, event_name, schema_version, organization_name in rows
            ]

        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=items,
        )
