from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import func
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentFilter, AgentRead, AgentTemplate
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@singleton
@dataclass
class AgentRepository:
    delegate: PostgresRepositoryDelegate

    def get_active(self, agent_id: UUID, org_id: UUID) -> Agent | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(Agent)
                .where(col(Agent.id) == agent_id)
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
            )
            return session.exec(query).first()

    def find_all_active(
        self,
        org_id: UUID,
        agent_filter: AgentFilter,
        pagination: Pagination,
    ) -> PaginatedItems[AgentRead]:
        with Session(self.delegate.engine) as session:
            query = (
                select(Agent)
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
            )

            if agent_filter.status is not None:
                query = query.where(col(Agent.status) == agent_filter.status)

            query = query.order_by(col(Agent.created_at).asc())

            count_query = (
                select(func.count())
                .select_from(Agent)
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.deleted_at).is_(None))
            )
            if agent_filter.status is not None:
                count_query = count_query.where(
                    col(Agent.status) == agent_filter.status
                )
            total = session.scalar(count_query) or 0

            query = query.offset((pagination.page - 1) * pagination.size).limit(
                pagination.size
            )

            items = [
                AgentRead.model_validate(agent) for agent in session.exec(query).all()
            ]

            return PaginatedItems(
                page=pagination.page,
                page_size=pagination.size,
                total=total,
                items=items,
            )

    def get_template_by_agent_and_version(
        self, agent_id: UUID, version: int, org_id: UUID
    ) -> AgentTemplate | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentTemplate)
                .where(col(AgentTemplate.agent_id) == agent_id)
                .where(col(AgentTemplate.version) == version)
                .where(col(AgentTemplate.organization_id) == org_id)
            )
            return session.exec(query).first()

    def get_template(self, template_id: UUID) -> AgentTemplate:
        template = self.delegate.find_by_id(AgentTemplate, template_id)
        if template is None:
            raise RuntimeError(f"AgentTemplate {template_id} not found")
        return template

    def save_template(self, template: AgentTemplate) -> AgentTemplate:
        self.delegate.save(template)
        return template

    def save(self, agent: Agent) -> Agent:
        self.delegate.save(agent)
        return agent
