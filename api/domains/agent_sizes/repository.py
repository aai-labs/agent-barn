from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlalchemy import func
from sqlmodel import Session, col, select

from api.domains.agent_sizes.models import SIZE_SETTINGS, AgentSize, OrganizationAgentSize
from api.domains.agents.models import Agent
from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    EVENT_REGISTRY,
    ORGANIZATION_AGENT_SIZES_CHANGED,
    PLATFORM_AGENT_SIZE_CHANGED,
    PLATFORM_AGENT_SIZE_CREATED,
    PLATFORM_AGENT_SIZE_DELETED,
)
from api.domains.events.models import EventScope
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.models import Organization
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class AgentSizeInUse(Exception):
    """An Agent row still references the size, so it can only be disabled."""


class AgentSizesNotAllowable(Exception):
    """Sizes that cannot be added to an Organization's allowed set: unknown or disabled."""

    def __init__(self, size_ids: set[UUID]) -> None:
        super().__init__(f"Agent sizes cannot be allowed: {sorted(map(str, size_ids))}")
        self.size_ids = size_ids


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

    def is_referenced(self, size_id: UUID, *, session: Session | None = None) -> bool:
        """Whether any Agent row is on this size, so it can only be disabled, not deleted.

        Soft-deleted Agents count: their rows still hold the reference, which the foreign
        key protects, and keeping the size keeps their history describing a real size.
        """
        query = select(Agent.id).where(col(Agent.agent_size_id) == size_id).limit(1)
        if session is not None:
            return session.exec(query).first() is not None
        with Session(self.delegate.engine) as own_session:
            return own_session.exec(query).first() is not None

    def agent_counts(self, organization_id: UUID | None = None) -> dict[UUID | None, int]:
        """Live Agents on each stored size, in one Organization when given. The None key
        counts the Agents that follow the default."""
        with Session(self.delegate.engine) as session:
            query = (
                select(Agent.agent_size_id, func.count())
                .where(col(Agent.deleted_at).is_(None))
                .group_by(col(Agent.agent_size_id))
            )
            if organization_id is not None:
                query = query.where(col(Agent.organization_id) == organization_id)
            return {size_id: count for size_id, count in session.exec(query)}

    def allowed_size_ids(self, organization_id: UUID) -> set[UUID]:
        """The sizes an Organization may choose beyond the default, enabled or not."""
        with Session(self.delegate.engine) as session:
            return set(
                session.exec(
                    select(OrganizationAgentSize.agent_size_id).where(
                        col(OrganizationAgentSize.organization_id) == organization_id
                    )
                )
            )

    def set_allowed_with_event(
        self, organization_id: UUID, size_ids: set[UUID], *, actor: ActorIdentity, actor_display: str
    ) -> list[UUID] | None:
        """Replace an Organization's allowed set and record the change, in one commit.

        The default is always choosable and never stored, so it is dropped from the set
        given. A size being added must exist and be enabled; one already in the set may stay
        after it was disabled, which is how a disabled size keeps the Agents already on it
        without being offered again. The Organization row is locked so two administrators'
        saves cannot both report the same "before". Returns the deliveries to dispatch
        (none when nothing changed), or None when the Organization does not exist. Raises
        AgentSizesNotAllowable.

        Lock order, shared with a default switch so neither deadlocks the other: every size
        row in id order (`_lock_sizes`). The Organization lock is `FOR NO KEY UPDATE`, so a
        switch inserting into this set, which key-share-locks the Organization through the
        foreign key, waits on the size rows instead of on it.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            organization = session.exec(
                select(Organization).where(col(Organization.id) == organization_id).with_for_update(key_share=True)
            ).first()
            if organization is None:
                return None
            sizes = {size.id: size for size in self._lock_sizes(session, read=True)}
            wanted = {size_id for size_id in size_ids if not (size_id in sizes and sizes[size_id].is_default)}
            current = set(
                session.exec(
                    select(OrganizationAgentSize.agent_size_id).where(
                        col(OrganizationAgentSize.organization_id) == organization_id
                    )
                )
            )
            added, removed = wanted - current, current - wanted
            refused = {size_id for size_id in added if size_id not in sizes or not sizes[size_id].enabled}
            if refused:
                raise AgentSizesNotAllowable(refused)
            if not added and not removed:
                return []

            for size_id in removed:
                session.delete(session.get(OrganizationAgentSize, (organization_id, size_id)))
            for size_id in added:
                session.add(OrganizationAgentSize(organization_id=organization_id, agent_size_id=size_id))
            session.flush()

            event_id = self._stage_allowed_changed(
                session, organization, sizes, wanted, current, actor, actor_display, uuid4()
            )
            delivery_ids = self._delivery_ids(session, [event_id])
            session.commit()
            return delivery_ids

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
        every size row locked in id order, the order an allowed-set save locks them in, so
        the catalog never has two defaults or none and neither write deadlocks the other.
        Every Organization that can choose is given the old default, so none loses a size it
        could choose. A value equal to the stored one records nothing. Returns None when the
        size does not exist.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            if changes.get("is_default"):
                size = next((locked for locked in self._lock_sizes(session) if locked.id == size_id), None)
            else:
                size = session.get(AgentSize, size_id, with_for_update=True)
            if size is None:
                return None

            # One save, one correlation: switching the default changes two sizes together.
            correlation_id = uuid4()
            moved: list[tuple[AgentSize, str, object, object]] = []
            allowed_event_ids: list[UUID] = []
            if changes.get("is_default") and not size.is_default:
                previous_default = session.exec(select(AgentSize).where(col(AgentSize.is_default))).one_or_none()
                if previous_default is not None:
                    previous_default.is_default = False
                    session.add(previous_default)
                    # The partial unique index allows one default, so the old one is cleared first.
                    session.flush()
                    moved.append((previous_default, "is_default", True, False))
                    allowed_event_ids = self._swap_default_in_allowed_sets(
                        session, size, previous_default, actor, correlation_id
                    )

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
            delivery_ids = self._delivery_ids(session, event_ids + allowed_event_ids)
            session.commit()
            session.refresh(size)
            return AgentSizeWriteResult(size=size, delivery_ids=delivery_ids)

    def delete_with_event(self, size_id: UUID, *, actor: Actor) -> AgentSizeWriteResult | None:
        """Delete a size nothing references. Raises AgentSizeInUse otherwise.

        Choosing a size for an Agent holds a share lock on the size row, so once this holds
        its update lock no Agent can start referencing it before the delete commits.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            size = session.get(AgentSize, size_id, with_for_update=True)
            if size is None:
                return None
            if self.is_referenced(size_id, session=session):
                raise AgentSizeInUse(size_id)
            event_id = self._stage(session, PLATFORM_AGENT_SIZE_DELETED, size, actor, self._values(size), uuid4())
            delivery_ids = self._delivery_ids(session, [event_id])
            session.delete(size)
            session.commit()
            return AgentSizeWriteResult(size=size, delivery_ids=delivery_ids)

    @staticmethod
    def _lock_sizes(session: Session, *, read: bool = False) -> list[AgentSize]:
        """Lock every size row in id order. Writes that lock more than one size row take
        them this way, so they wait on each other instead of deadlocking."""
        return list(session.exec(select(AgentSize).order_by(col(AgentSize.id)).with_for_update(read=read)).all())

    def _swap_default_in_allowed_sets(
        self, session: Session, new_default: AgentSize, old_default: AgentSize, actor: Actor, correlation_id: UUID
    ) -> list[UUID]:
        """Give the old default to every Organization that can choose, recording each set.

        An allowed set never stores the default, so without this an Organization that can
        choose would lose the old default, and one that listed the new default would lose
        that too. Each keeps every size it could choose, and the new default joins them as
        it does for everyone. An Organization that cannot choose still just follows the
        default. The caller holds every size row's update lock, so an allowed-set save
        for any of these Organizations is waiting on it and reads the result.
        """
        organization_ids = list(session.exec(select(OrganizationAgentSize.organization_id).distinct()))
        if not organization_ids:
            return []
        sizes = {size.id: size for size in session.exec(select(AgentSize)).all()}
        event_ids = []
        for organization_id in organization_ids:
            organization = session.get(Organization, organization_id)
            current = set(
                session.exec(
                    select(OrganizationAgentSize.agent_size_id).where(
                        col(OrganizationAgentSize.organization_id) == organization_id
                    )
                )
            )
            if new_default.id in current:
                session.delete(session.get(OrganizationAgentSize, (organization_id, new_default.id)))
            if old_default.id not in current:
                session.add(OrganizationAgentSize(organization_id=organization_id, agent_size_id=old_default.id))
            session.flush()
            wanted = (current - {new_default.id}) | {old_default.id}
            if organization is not None:
                event_ids.append(
                    self._stage_allowed_changed(
                        session,
                        organization,
                        sizes,
                        wanted,
                        current,
                        ActorIdentity(type=ActorIdentityType.USER, id=actor.user_id),
                        actor.display,
                        correlation_id,
                    )
                )
        return event_ids

    def _stage_allowed_changed(
        self,
        session: Session,
        organization: Organization,
        sizes: Mapping[UUID, AgentSize],
        wanted: set[UUID],
        current: set[UUID],
        actor: ActorIdentity,
        actor_display: str,
        correlation_id: UUID,
    ) -> UUID:
        def ordered(ids: set[UUID]) -> list[AgentSize]:
            return sorted((sizes[size_id] for size_id in ids), key=lambda size: (size.sort_order, size.name))

        event = EVENT_REGISTRY.build_event(
            event_name=ORGANIZATION_AGENT_SIZES_CHANGED,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization.id,
            actor=actor,
            subject=SubjectIdentity(
                type=SubjectIdentityType.ORGANIZATION,
                id=organization.id,
                organization_id=organization.id,
            ),
            correlation_id=correlation_id,
            payload={
                "organization_id": organization.id,
                "agent_size_ids": [size.id for size in ordered(wanted)],
                "agent_size_names": [size.name for size in ordered(wanted)],
                "previous_agent_size_ids": [size.id for size in ordered(current)],
                "previous_agent_size_names": [size.name for size in ordered(current)],
                "actor_display": actor_display,
                "subject_display": organization.name,
            },
        )
        self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
        return event.event_id

    @staticmethod
    def _values(size: AgentSize) -> dict[str, object]:
        return {
            "cpu_request_millicores": size.cpu_request_millicores,
            "cpu_limit_millicores": size.cpu_limit_millicores,
            "memory_request_bytes": size.memory_request_bytes,
            "memory_limit_bytes": size.memory_limit_bytes,
            "storage_bytes": size.storage_bytes,
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
