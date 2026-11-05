from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.events import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import AGENT_UPDATED, EVENT_REGISTRY
from api.domains.events.repository import OutboxMessageRepository
from api.domains.personas.models import AgentPersona, AgentPersonaVersion
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class PersonaRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def list_active_in_scope(self, agent_id: UUID, authorization_scope: AuthorizationScope) -> list[AgentPersona]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(AgentPersona)
                    .join(Agent, col(Agent.id) == col(AgentPersona.agent_id))
                    .where(
                        col(AgentPersona.agent_id) == agent_id,
                        col(AgentPersona.deleted_at).is_(None),
                        *agent_scope_predicates(authorization_scope),
                    )
                    .order_by(col(AgentPersona.created_at), col(AgentPersona.id))
                ).all()
            )

    def get_active_in_scope(
        self,
        agent_id: UUID,
        key: str,
        authorization_scope: AuthorizationScope,
    ) -> AgentPersona | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentPersona)
                .join(Agent, col(Agent.id) == col(AgentPersona.agent_id))
                .where(
                    col(AgentPersona.agent_id) == agent_id,
                    col(AgentPersona.key) == key,
                    col(AgentPersona.deleted_at).is_(None),
                    *agent_scope_predicates(authorization_scope),
                )
            ).one_or_none()

    def list_all_keys_in_scope(self, agent_id: UUID, authorization_scope: AuthorizationScope) -> list[str]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(AgentPersona.key)
                    .join(Agent, col(Agent.id) == col(AgentPersona.agent_id))
                    .where(col(AgentPersona.agent_id) == agent_id, *agent_scope_predicates(authorization_scope))
                ).all()
            )

    def create_with_event(
        self,
        persona: AgentPersona,
        version: AgentPersonaVersion,
        agent: Agent,
        actor: ActorIdentity,
        actor_display: str,
    ) -> list[UUID]:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            session.add(persona)
            session.flush()
            session.add(version)
            deliveries = self._stage_change(session, persona.key, "created", agent, actor, actor_display)
            session.commit()
            return deliveries

    def update_with_event(
        self,
        persona_id: UUID,
        display_name: str,
        emoji: str | None,
        version: AgentPersonaVersion | None,
        agent: Agent,
        actor: ActorIdentity,
        actor_display: str,
    ) -> tuple[AgentPersona, list[UUID]]:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            persona = session.get_one(AgentPersona, persona_id)
            persona.display_name = display_name
            persona.emoji = emoji
            if version is not None:
                session.add(version)
                persona.current_version = version.version
            session.add(persona)
            deliveries = self._stage_change(session, persona.key, "updated", agent, actor, actor_display)
            session.commit()
            return persona, deliveries

    def _stage_change(
        self,
        session: Session,
        key: str,
        operation: str,
        agent: Agent,
        actor: ActorIdentity,
        actor_display: str,
    ) -> list[UUID]:
        event = EVENT_REGISTRY.build_event(
            event_name=AGENT_UPDATED,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=agent.organization_id,
            actor=actor,
            subject=SubjectIdentity(type=SubjectIdentityType.AGENT, id=agent.id, organization_id=agent.organization_id),
            correlation_id=uuid4(),
            payload={
                "organization_id": agent.organization_id,
                "agent_id": agent.id,
                "field_changes": {f"personas.{key}": {"previous": None, "new": operation}},
                "actor_display": actor_display,
                "subject_display": agent.name,
            },
        )
        self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
        return list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))

    def get_version(self, persona_id: UUID, version: int) -> AgentPersonaVersion | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentPersonaVersion).where(
                    col(AgentPersonaVersion.persona_id) == persona_id,
                    col(AgentPersonaVersion.version) == version,
                )
            ).one_or_none()

    def list_versions(self, persona_id: UUID) -> list[AgentPersonaVersion]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(AgentPersonaVersion)
                    .where(col(AgentPersonaVersion.persona_id) == persona_id)
                    .order_by(col(AgentPersonaVersion.version).desc())
                ).all()
            )
