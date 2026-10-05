from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, select

from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY, PLATFORM_RESOURCE_LIMITS_CHANGED
from api.domains.events.models import EventScope
from api.domains.events.repository import OutboxMessageRepository
from api.domains.resource_limits.models import (
    PLATFORM_RESOURCE_LIMITS_ID,
    SUBJECT_DISPLAY,
    PlatformResourceLimits,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@dataclass(frozen=True)
class ResourceLimitsChangeResult:
    limits: PlatformResourceLimits | None
    # Empty when nothing changed, so there is nothing to dispatch.
    delivery_ids: list[UUID]


@inject
@singleton
@dataclass
class ResourceLimitsRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def get(self) -> PlatformResourceLimits | None:
        with Session(self.delegate.engine) as session:
            return session.get(PlatformResourceLimits, PLATFORM_RESOURCE_LIMITS_ID)

    def set_with_events(
        self,
        changes: Mapping[str, int | float | None],
        *,
        actor_user_id: UUID,
        actor_display: str,
    ) -> ResourceLimitsChangeResult:
        """Persists the limits and stages one change Event per limit that moved, atomically.

        The row and the Events share one session and one commit, so a change can never be
        visible without its audit record. The row is locked while it is read, so two
        administrators saving at once cannot both record the same "previous" value. A value
        that equals the stored one is not a transition and writes nothing.

        `SELECT ... FOR UPDATE` locks only a row that already exists, so on the very first
        save, with no row yet, two administrators would both INSERT it and one would fail on
        the primary key. The row is therefore created first with `ON CONFLICT DO NOTHING`,
        in this same transaction: a second INSERT waits for the first to commit or roll back,
        then does nothing, and both reach the locked read in turn.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            created_at = datetime.now(UTC)
            # On the session's own connection, so it is part of this transaction.
            inserted = (
                session.connection()
                .execute(
                    pg_insert(PlatformResourceLimits)
                    .values(id=PLATFORM_RESOURCE_LIMITS_ID, created_at=created_at, updated_at=created_at)
                    .on_conflict_do_nothing(index_elements=["id"])
                )
                .rowcount
            )
            limits = session.get(PlatformResourceLimits, PLATFORM_RESOURCE_LIMITS_ID, with_for_update=True)
            assert limits is not None  # inserted above, or already there

            moved: list[tuple[str, int | float | None, int | float | None]] = []
            for setting, value in changes.items():
                previous = getattr(limits, setting)
                if previous != value:
                    moved.append((setting, previous, value))
                    setattr(limits, setting, value)
            if not moved:
                # Nothing to save, and nothing is committed: closing the session rolls back a
                # row created above, so it is reported as absent, as the database would say.
                return ResourceLimitsChangeResult(limits=None if inserted else limits, delivery_ids=[])

            now = datetime.now(UTC)
            limits.updated_at = now
            session.add(limits)
            session.flush()

            correlation_id = uuid4()
            event_ids = []
            for setting, previous, current in moved:
                event = EVENT_REGISTRY.build_event(
                    event_name=PLATFORM_RESOURCE_LIMITS_CHANGED,
                    schema_version=1,
                    occurred_at=now,
                    event_scope=EventScope.PLATFORM,
                    organization_id=None,
                    actor=ActorIdentity(type=ActorIdentityType.USER, id=actor_user_id),
                    subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id=PLATFORM_RESOURCE_LIMITS_ID),
                    correlation_id=correlation_id,
                    payload={
                        "actor_user_id": actor_user_id,
                        "actor_display": actor_display,
                        "subject_display": SUBJECT_DISPLAY,
                        "setting": setting,
                        "previous": None if previous is None else float(previous),
                        "current": None if current is None else float(current),
                    },
                )
                self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
                event_ids.append(event.event_id)

            delivery_ids = list(
                session.exec(select(EventDelivery.id).where(col(EventDelivery.event_id).in_(event_ids)))
            )
            session.commit()
            session.refresh(limits)
            return ResourceLimitsChangeResult(limits=limits, delivery_ids=delivery_ids)
