from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from sqlmodel import Session, SQLModel, col, select

from api.domains.agent_memory.gateway_models import MemoryAccess
from api.domains.agent_memory.models import AgentMemoryGrant
from api.domains.agents.models import Agent, AgentStatus
from api.domains.events import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    AGENT_MEMORY_DISABLED,
    AGENT_MEMORY_ENABLED,
    AGENT_MEMORY_GRANT_CREATED,
    AGENT_MEMORY_GRANT_REVOKED,
    EVENT_REGISTRY,
)
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.models import Organization
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def stage_agent_memory_cleanup(session: Session, agent_id: UUID, organization_id: UUID, now: datetime) -> None:
    """Stage grant removal and a tombstone in the caller's Agent deletion transaction."""
    session.exec(
        sa.delete(AgentMemoryGrant).where(
            col(AgentMemoryGrant.organization_id) == organization_id,
            sa.or_(col(AgentMemoryGrant.agent_id) == agent_id, col(AgentMemoryGrant.source_agent_id) == agent_id),
        )
    )
    statement = (
        pg_insert(SQLModel.metadata.tables["agent_memory_purge"])
        .values(
            id=uuid4(),
            agent_id=agent_id,
            organization_id=organization_id,
            created_at=now,
            updated_at=now,
            next_attempt_at=now,
            attempts=0,
        )
        .on_conflict_do_nothing(index_elements=["agent_id"])
    )
    session.exec(statement)  # type: ignore[call-overload]


class AgentMemoryGrantTargetGoneError(ValueError):
    """An Agent disappeared after the service authorized a grant."""


class AgentMemoryGrantConflictError(Exception):
    pass


@dataclass(frozen=True)
class AgentMemoryGrantRow:
    grant: AgentMemoryGrant
    agent_name: str
    source_agent_name: str | None


@dataclass(frozen=True)
class AgentMemoryGrantChangeResult:
    grant: AgentMemoryGrant
    delivery_ids: list[UUID]


@inject
@singleton
@dataclass
class AgentMemoryRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def resolve_memory_access(self, key_hash: str) -> MemoryAccess | None:
        """Machine credentials select one live Agent; grants are reloaded each request."""
        with Session(self.delegate.engine) as session:
            agent = session.exec(
                select(Agent)
                .join(Organization, col(Organization.id) == col(Agent.organization_id))
                .where(
                    col(Agent.memory_key_hash) == key_hash,
                    col(Agent.deleted_at).is_(None),
                    col(Agent.status) == AgentStatus.RUNNING,
                    col(Agent.memory_enabled).is_(True),
                )
            ).first()
            if agent is None:
                return None
            source = aliased(Agent)
            grants = session.exec(
                select(AgentMemoryGrant)
                .outerjoin(source, col(source.id) == col(AgentMemoryGrant.source_agent_id))
                .where(
                    col(AgentMemoryGrant.organization_id) == agent.organization_id,
                    col(AgentMemoryGrant.agent_id) == agent.id,
                    col(source.deleted_at).is_(None),
                )
            ).all()
            organization_memory_write = any(
                grant.source_agent_id is None and grant.access == "read_write" for grant in grants
            )
            tags = [f"agent:{agent.id}"]
            tags.extend(
                sorted(f"agent:{grant.source_agent_id}" for grant in grants if grant.source_agent_id is not None)
            )
            if any(grant.source_agent_id is None for grant in grants):
                tags.append("scope:team")
            return MemoryAccess(agent.id, agent.organization_id, tuple(tags), organization_memory_write)

    def has_organization_memory_read(self, organization_id: UUID, agent_id: UUID) -> bool:
        """Current read/read-write grant, independent of runtime state and memory opt-in."""
        with Session(self.delegate.engine) as session:
            return (
                session.exec(
                    select(AgentMemoryGrant.id).where(
                        col(AgentMemoryGrant.organization_id) == organization_id,
                        col(AgentMemoryGrant.agent_id) == agent_id,
                        col(AgentMemoryGrant.source_agent_id).is_(None),
                    )
                ).first()
                is not None
            )

    def resolve_view_target(self, organization_id: UUID, agent_id: UUID | None) -> bool:
        """Whether the Organization exists and any targeted Agent is undeleted within it.

        Stored memories stay viewable while memory is off and the Agent is stopped.
        """
        with Session(self.delegate.engine) as session:
            if agent_id is None:
                return session.get(Organization, organization_id) is not None
            return (
                session.exec(
                    select(Agent.id)
                    .join(Organization, col(Organization.id) == col(Agent.organization_id))
                    .where(
                        col(Agent.id) == agent_id,
                        col(Agent.organization_id) == organization_id,
                        col(Agent.deleted_at).is_(None),
                    )
                ).first()
                is not None
            )

    def set_enabled_with_event(
        self,
        agent_id: UUID,
        organization_id: UUID,
        enabled: bool,
        *,
        actor: ActorIdentity,
        actor_display: str,
    ) -> list[UUID] | None:
        """Persist the toggle and Event, or return None if the Agent disappeared."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            agent = session.exec(
                select(Agent)
                .where(
                    col(Agent.id) == agent_id,
                    col(Agent.organization_id) == organization_id,
                    col(Agent.deleted_at).is_(None),
                )
                .with_for_update()
            ).one_or_none()
            if agent is None:
                return None
            if agent.memory_enabled == enabled:
                return []
            agent.memory_enabled = enabled
            session.add(agent)
            session.flush()
            event_id = self._stage(
                session,
                event_name=AGENT_MEMORY_ENABLED if enabled else AGENT_MEMORY_DISABLED,
                organization_id=organization_id,
                agent_id=agent_id,
                actor=actor,
                payload={
                    "organization_id": organization_id,
                    "agent_id": agent_id,
                    "actor_display": actor_display,
                    "subject_display": agent.name,
                },
            )
            delivery_ids = self._delivery_ids(session, event_id)
            session.commit()
            return delivery_ids

    def list_grants(self, organization_id: UUID) -> list[AgentMemoryGrantRow]:
        """Grants whose reading and source Agents are both still active."""
        reader = aliased(Agent)
        source = aliased(Agent)
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentMemoryGrant, reader.name, source.name)
                .join(reader, col(reader.id) == col(AgentMemoryGrant.agent_id))
                .outerjoin(source, col(source.id) == col(AgentMemoryGrant.source_agent_id))
                .where(
                    col(AgentMemoryGrant.organization_id) == organization_id,
                    col(reader.deleted_at).is_(None),
                    (col(AgentMemoryGrant.source_agent_id).is_(None)) | (col(source.deleted_at).is_(None)),
                )
                .order_by(col(reader.name), col(AgentMemoryGrant.source_agent_id).is_not(None), col(source.name))
            )
            return [
                AgentMemoryGrantRow(grant=grant, agent_name=agent_name, source_agent_name=source_name)
                for grant, agent_name, source_name in session.exec(query).all()
            ]

    def get_grant(self, organization_id: UUID, grant_id: UUID) -> AgentMemoryGrant | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentMemoryGrant).where(
                    col(AgentMemoryGrant.id) == grant_id,
                    col(AgentMemoryGrant.organization_id) == organization_id,
                )
            ).first()

    def create_grant_with_event(
        self,
        grant: AgentMemoryGrant,
        *,
        agent_name: str,
        source_display: str,
        actor: ActorIdentity,
        actor_display: str,
    ) -> AgentMemoryGrantChangeResult:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            # Hold shared row locks through insertion so a concurrent soft delete
            # either removes this grant afterward or makes this transaction refuse it.
            ids = {grant.agent_id}
            if grant.source_agent_id:
                ids.add(grant.source_agent_id)
            targets = session.exec(
                select(Agent.id)
                .where(
                    col(Agent.id).in_(ids),
                    col(Agent.organization_id) == grant.organization_id,
                    col(Agent.deleted_at).is_(None),
                )
                .order_by(col(Agent.id))
                .with_for_update(read=True)
            ).all()
            if len(targets) != len(ids):
                raise AgentMemoryGrantTargetGoneError("Memory grant Agent not found.")
            session.add(grant)
            try:
                session.flush()
            except IntegrityError as exc:
                session.rollback()
                raise AgentMemoryGrantConflictError("This Agent already has that memory grant.") from exc
            event_id = self._stage_grant_event(
                session,
                AGENT_MEMORY_GRANT_CREATED,
                grant,
                agent_name=agent_name,
                source_display=source_display,
                actor=actor,
                actor_display=actor_display,
            )
            delivery_ids = self._delivery_ids(session, event_id)
            session.commit()
            return AgentMemoryGrantChangeResult(grant=grant, delivery_ids=delivery_ids)

    def revoke_grant_with_event(
        self,
        grant: AgentMemoryGrant,
        *,
        agent_name: str,
        source_display: str,
        actor: ActorIdentity,
        actor_display: str,
    ) -> list[UUID]:
        with Session(self.delegate.engine) as session:
            stored = session.get(AgentMemoryGrant, grant.id)
            if stored is None:
                return []
            session.delete(stored)
            session.flush()
            event_id = self._stage_grant_event(
                session,
                AGENT_MEMORY_GRANT_REVOKED,
                grant,
                agent_name=agent_name,
                source_display=source_display,
                actor=actor,
                actor_display=actor_display,
            )
            delivery_ids = self._delivery_ids(session, event_id)
            session.commit()
            return delivery_ids

    def _stage_grant_event(
        self,
        session: Session,
        event_name: str,
        grant: AgentMemoryGrant,
        *,
        agent_name: str,
        source_display: str,
        actor: ActorIdentity,
        actor_display: str,
    ) -> UUID:
        return self._stage(
            session,
            event_name=event_name,
            organization_id=grant.organization_id,
            agent_id=grant.agent_id,
            actor=actor,
            payload={
                "organization_id": grant.organization_id,
                "grant_id": grant.id,
                "agent_id": grant.agent_id,
                "source_agent_id": grant.source_agent_id,
                "access": grant.access,
                "source_display": source_display,
                "actor_display": actor_display,
                "subject_display": agent_name,
            },
        )

    def _stage(
        self,
        session: Session,
        *,
        event_name: str,
        organization_id: UUID,
        agent_id: UUID,
        actor: ActorIdentity,
        payload: dict[str, Any],
    ) -> UUID:
        event = EVENT_REGISTRY.build_event(
            event_name=event_name,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=actor,
            subject=SubjectIdentity(type=SubjectIdentityType.AGENT, id=agent_id, organization_id=organization_id),
            correlation_id=uuid4(),
            payload=payload,
        )
        self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
        return event.event_id

    @staticmethod
    def _delivery_ids(session: Session, event_id: UUID) -> list[UUID]:
        return list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event_id)))
