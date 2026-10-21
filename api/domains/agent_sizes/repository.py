from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlalchemy import func
from sqlmodel import Session, col, select

from api.domains.agent_sizes.models import SIZE_SETTINGS, AgentSize
from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    EVENT_REGISTRY,
    PLATFORM_AGENT_SIZE_CHANGED,
    PLATFORM_AGENT_SIZE_CREATED,
    PLATFORM_AGENT_SIZE_DELETED,
)
from api.domains.events.models import EventScope
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@dataclass(frozen=True)
class Actor:
    user_id: UUID
    display: str


@dataclass(frozen=True)
class AgentSizeWriteResult:
    size: AgentSize
    # Empty when nothing changed, so there is nothing to dispatch.
    delivery_ids: list[UUID]


@inject
@singleton
@dataclass
class AgentSizeRepository:
    """The Agent Size catalog. Every write and its audit Events commit together."""

    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def list_all(self) -> list[AgentSize]:
        with Session(self.delegate.engine) as session:
            query = select(AgentSize).order_by(col(AgentSize.sort_order), col(AgentSize.name))
            return list(session.exec(query).all())

    def get(self, size_id: UUID) -> AgentSize | None:
        with Session(self.delegate.engine) as session:
            return session.get(AgentSize, size_id)

    def get_default(self) -> AgentSize | None:
        with Session(self.delegate.engine) as session:
            return session.exec(select(AgentSize).where(col(AgentSize.is_default))).one_or_none()

    def name_taken(self, name: str, *, excluding: UUID | None = None) -> bool:
        """Whether another size already has this name, ignoring case and surrounding space."""
        with Session(self.delegate.engine) as session:
            query = select(AgentSize.id).where(func.lower(col(AgentSize.name)) == name.strip().lower())
            if excluding is not None:
                query = query.where(col(AgentSize.id) != excluding)
            return session.exec(query).first() is not None

    def is_referenced(self, size_id: UUID) -> bool:
        """Whether any Agent is on this size, so it can only be disabled, not deleted.

        Nothing references a size until Agents can be given one (Agent Sizes PR 2 adds
        `agent.agent_size_id`); that slice makes this answer for real.
        """
        return False

    def create_with_event(self, size: AgentSize, *, actor: Actor) -> AgentSizeWriteResult:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            session.add(size)
            session.flush()
            event_id = self._stage(session, PLATFORM_AGENT_SIZE_CREATED, size, actor, self._values(size), uuid4())
            delivery_ids = self._delivery_ids(session, [event_id])
            session.commit()
            session.refresh(size)
            return AgentSizeWriteResult(size=size, delivery_ids=delivery_ids)

    def update_with_events(
        self, size_id: UUID, changes: Mapping[str, object], *, actor: Actor
    ) -> AgentSizeWriteResult | None:
        """Apply the changes and record one change Event per field that moved.

        Making a size the default clears the old default in the same transaction, with
        both rows locked, so the catalog never has two defaults or none, even when two
        administrators switch it at once. A value equal to the stored one records nothing.
        Returns None when the size does not exist.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            size = session.get(AgentSize, size_id, with_for_update=True)
            if size is None:
                return None

            moved: list[tuple[AgentSize, str, object, object]] = []
            if changes.get("is_default") and not size.is_default:
                previous_default = session.exec(
                    select(AgentSize).where(col(AgentSize.is_default)).with_for_update()
                ).one_or_none()
                if previous_default is not None:
                    previous_default.is_default = False
                    session.add(previous_default)
                    # The partial unique index allows one default, so the old one is cleared first.
                    session.flush()
                    moved.append((previous_default, "is_default", True, False))

            for setting in SIZE_SETTINGS:
                if setting not in changes:
                    continue
                previous, current = getattr(size, setting), changes[setting]
                if previous != current:
                    setattr(size, setting, current)
                    moved.append((size, setting, previous, current))

            if not moved:
                return AgentSizeWriteResult(size=size, delivery_ids=[])

            session.add(size)
            session.flush()
            # One save, one correlation: switching the default changes two sizes together.
            correlation_id = uuid4()
            event_ids = [
                self._stage(
                    session,
                    PLATFORM_AGENT_SIZE_CHANGED,
                    changed,
                    actor,
                    {"setting": setting, "previous": previous, "current": current},
                    correlation_id,
                )
                for changed, setting, previous, current in moved
            ]
            delivery_ids = self._delivery_ids(session, event_ids)
            session.commit()
            session.refresh(size)
            return AgentSizeWriteResult(size=size, delivery_ids=delivery_ids)

    def delete_with_event(self, size_id: UUID, *, actor: Actor) -> AgentSizeWriteResult | None:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            size = session.get(AgentSize, size_id, with_for_update=True)
            if size is None:
                return None
            event_id = self._stage(session, PLATFORM_AGENT_SIZE_DELETED, size, actor, self._values(size), uuid4())
            delivery_ids = self._delivery_ids(session, [event_id])
            session.delete(size)
            session.commit()
            return AgentSizeWriteResult(size=size, delivery_ids=delivery_ids)

    @staticmethod
    def _values(size: AgentSize) -> dict[str, object]:
        return {
            "cpu_request_millicores": size.cpu_request_millicores,
            "cpu_limit_millicores": size.cpu_limit_millicores,
            "memory_request_bytes": size.memory_request_bytes,
            "memory_limit_bytes": size.memory_limit_bytes,
            "enabled": size.enabled,
            "is_default": size.is_default,
        }

    def _stage(
        self,
        session: Session,
        event_name: str,
        size: AgentSize,
        actor: Actor,
        payload: Mapping[str, object],
        correlation_id: UUID,
    ) -> UUID:
        event = EVENT_REGISTRY.build_event(
            event_name=event_name,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            event_scope=EventScope.PLATFORM,
            organization_id=None,
            actor=ActorIdentity(type=ActorIdentityType.USER, id=actor.user_id),
            subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id=size.id),
            correlation_id=correlation_id,
            payload={
                "actor_user_id": actor.user_id,
                "actor_display": actor.display,
                "subject_display": size.name,
                **payload,
            },
        )
        self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
        return event.event_id

    @staticmethod
    def _delivery_ids(session: Session, event_ids: list[UUID]) -> list[UUID]:
        return list(session.exec(select(EventDelivery.id).where(col(EventDelivery.event_id).in_(event_ids))))
