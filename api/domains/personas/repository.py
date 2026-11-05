from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.personas.models import AgentPersona, AgentPersonaVersion
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class PersonaRepository:
    delegate: PostgresRepositoryDelegate

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
