from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.events import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY, MEMORY_GROUP_DELETED
from api.domains.events.repository import OutboxMessageRepository
from api.domains.memory_groups.exceptions import MemoryGroupNameConflictHTTPException
from api.domains.memory_groups.models import MemoryGroup
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class MemoryGroupRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def save(self, group: MemoryGroup) -> MemoryGroup:
        try:
            self.delegate.save(group)
        except IntegrityError as e:
            if "uq_memory_group_org_name" in str(e).lower():
                raise MemoryGroupNameConflictHTTPException(group.name)
            raise
        return group

    def get_by_id_and_org(self, group_id: UUID, org_id: UUID) -> MemoryGroup | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(MemoryGroup)
                .where(col(MemoryGroup.id) == group_id)
                .where(col(MemoryGroup.organization_id) == org_id)
            )
            return session.exec(query).first()

    def find_all_for_org(self, org_id: UUID) -> list[MemoryGroup]:
        with Session(self.delegate.engine) as session:
            query = (
                select(MemoryGroup)
                .where(col(MemoryGroup.organization_id) == org_id)
                .order_by(col(MemoryGroup.name).asc())
            )
            return list(session.exec(query).all())

    def find_all(self) -> list[MemoryGroup]:
        """Every group across every Organization. System callers only."""
        with Session(self.delegate.engine) as session:
            return list(session.exec(select(MemoryGroup)).all())

    def delete(self, group: MemoryGroup) -> None:
        self.delegate.delete(group)

    def delete_with_purge_event(
        self,
        group: MemoryGroup,
        *,
        workspace_id: str,
        actor: ActorIdentity,
        correlation_id: UUID | None = None,
    ) -> list[UUID]:
        """Delete the group row and stage the pool-purge event in one transaction.

        Atomic on purpose: the group is gone and the durable purge is queued
        together, or neither happens. The pool workspace id is carried in the event
        payload (not looked up from the now-deleted row), and the retried delivery
        erases the workspace past Honcho's async session-delete race. Members'
        `memory_group_id` clears via the FK (SET NULL). Returns the delivery ids to
        enqueue immediately after commit.
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            persisted = session.exec(select(MemoryGroup).where(col(MemoryGroup.id) == group.id)).first()
            if persisted is None:
                return []
            organization_id = persisted.organization_id
            session.delete(persisted)
            session.flush()
            event = EVENT_REGISTRY.build_event(
                event_name=MEMORY_GROUP_DELETED,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.ORGANIZATION,
                    id=group.id,
                    organization_id=organization_id,
                ),
                correlation_id=correlation_id or uuid4(),
                payload={
                    "organization_id": organization_id,
                    "group_id": group.id,
                    "workspace_id": workspace_id,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return delivery_ids
