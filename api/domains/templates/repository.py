from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import func, or_
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, select

from api.domains.templates.models import AgentTemplate, TemplateFilter
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import Pagination


@inject
@singleton
@dataclass
class TemplateRepository:
    delegate: PostgresRepositoryDelegate

    def get_template_by_slug_and_version(
        self, org_id: UUID, slug: str, version: int
    ) -> AgentTemplate | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentTemplate)
                .where(col(AgentTemplate.organization_id) == org_id)
                .where(col(AgentTemplate.template_slug) == slug)
                .where(col(AgentTemplate.version) == version)
            )
            return session.exec(query).first()

    def get_template_or_raise(
        self, org_id: UUID, slug: str, version: int
    ) -> AgentTemplate:
        template = self.get_template_by_slug_and_version(org_id, slug, version)
        if template is None:
            raise RuntimeError(f"AgentTemplate {slug} v{version} not found")
        return template

    def get_latest_template(self, org_id: UUID, slug: str) -> AgentTemplate | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentTemplate)
                .where(col(AgentTemplate.organization_id) == org_id)
                .where(col(AgentTemplate.template_slug) == slug)
                .order_by(col(AgentTemplate.version).desc())
                .limit(1)
            )
            return session.exec(query).first()

    def find_latest_templates(
        self,
        org_id: UUID,
        template_filter: TemplateFilter,
        pagination: Pagination,
    ) -> tuple[list[AgentTemplate], int]:
        with Session(self.delegate.engine) as session:
            # Postgres DISTINCT ON (template_slug) keeps the first row per slug;
            # ordering by version DESC makes that row the latest. Filters apply
            # to the latest rows (outer query), not historical versions.
            latest = (
                select(AgentTemplate)
                .where(col(AgentTemplate.organization_id) == org_id)
                .distinct(col(AgentTemplate.template_slug))
                .order_by(
                    col(AgentTemplate.template_slug).asc(),
                    col(AgentTemplate.version).desc(),
                )
                .subquery()
            )
            latest_template = aliased(AgentTemplate, latest)

            conditions = []
            if template_filter.search:
                pattern = f"%{template_filter.search}%"
                conditions.append(
                    or_(
                        col(latest_template.template_name).ilike(pattern),
                        col(latest_template.template_slug).ilike(pattern),
                    )
                )
            if template_filter.source is not None:
                conditions.append(
                    col(latest_template.template_source) == template_filter.source
                )

            count_query = select(func.count()).select_from(latest)
            for condition in conditions:
                count_query = count_query.where(condition)
            total = session.scalar(count_query) or 0

            query = select(latest_template)
            for condition in conditions:
                query = query.where(condition)
            query = (
                query.order_by(col(latest_template.template_name).asc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            )
            templates = list(session.exec(query).all())
            return templates, total

    def save_template(self, template: AgentTemplate) -> AgentTemplate:
        self.delegate.save(template)
        return template
