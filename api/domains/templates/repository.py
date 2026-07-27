from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import case, func, or_
from sqlalchemy.orm import aliased
from sqlmodel import Session, col, delete, select, update

from api.domains.agents.models import Agent, AgentTemplateSkill
from api.domains.skills.models import Skill
from api.domains.templates.models import AgentTemplate, TemplateFilter, TemplateSource
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

    def find_versions(self, org_id: UUID, slug: str) -> list[AgentTemplate]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentTemplate)
                .where(col(AgentTemplate.organization_id) == org_id)
                .where(col(AgentTemplate.template_slug) == slug)
                .order_by(col(AgentTemplate.version).desc())
            )
            return list(session.exec(query).all())

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
                query.order_by(
                    case(
                        (
                            col(latest_template.template_source)
                            == TemplateSource.PRE_DEFINED,
                            0,
                        ),
                        else_=1,
                    ).asc(),
                    col(latest_template.template_name).asc(),
                )
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            )
            templates = list(session.exec(query).all())
            return templates, total

    def save_template(self, template: AgentTemplate) -> AgentTemplate:
        self.delegate.save(template)
        return template

    def get_slugs_used_by_live_agents(self, org_id: UUID, slugs: list[str]) -> set[str]:
        if not slugs:
            return set()
        with Session(self.delegate.engine) as session:
            query = (
                select(Agent.template_slug)
                .distinct()
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.template_slug).in_(slugs))
                .where(col(Agent.deleted_at).is_(None))
            )
            return {slug for slug in session.exec(query).all() if slug is not None}

    def is_lineage_used_by_live_agent(self, org_id: UUID, slug: str) -> bool:
        with Session(self.delegate.engine) as session:
            query = (
                select(Agent)
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.template_slug) == slug)
                .where(col(Agent.deleted_at).is_(None))
            )
            return session.exec(query).first() is not None

    def purge_template_lineage(self, org_id: UUID, slug: str) -> None:
        """Delete every version of a lineage, detaching soft-deleted agents first.

        Soft-deleted agents keep their row (and its RESTRICT FK); NULLing their
        pin lifts the constraint. Both statements share one transaction, so a
        concurrently created live agent surfaces as IntegrityError on commit.
        agent_template_skill rows cascade at the DB level.
        """
        with Session(self.delegate.engine) as session:
            detach = (
                update(Agent)
                .where(col(Agent.organization_id) == org_id)
                .where(col(Agent.template_slug) == slug)
                .where(col(Agent.deleted_at).is_not(None))
                .values(template_slug=None, template_version=None)
            )
            session.exec(detach)  # type: ignore[call-overload]
            purge = (
                delete(AgentTemplate)
                .where(col(AgentTemplate.organization_id) == org_id)
                .where(col(AgentTemplate.template_slug) == slug)
            )
            session.exec(purge)  # type: ignore[call-overload]
            session.commit()

    def save_template_skills(self, template_id: UUID, skill_ids: list[UUID]) -> None:
        with Session(self.delegate.engine) as session:
            existing_rows = session.exec(
                select(AgentTemplateSkill).where(
                    col(AgentTemplateSkill.template_id) == template_id
                )
            ).all()
            existing_ids = {row.skill_id for row in existing_rows}
            target_ids = set(skill_ids)
            for row in existing_rows:
                if row.skill_id not in target_ids:
                    session.delete(row)
            for skill_id in target_ids - existing_ids:
                session.add(
                    AgentTemplateSkill(template_id=template_id, skill_id=skill_id)
                )
            session.commit()

    def get_required_skills(self, template_id: UUID) -> list[Skill]:
        with Session(self.delegate.engine) as session:
            query = (
                select(Skill)
                .join(
                    AgentTemplateSkill,
                    col(AgentTemplateSkill.skill_id) == col(Skill.id),
                )
                .where(col(AgentTemplateSkill.template_id) == template_id)
            )
            return list(session.exec(query).all())

    def get_required_skill_ids(self, template_id: UUID) -> set[UUID]:
        with Session(self.delegate.engine) as session:
            query = select(AgentTemplateSkill.skill_id).where(
                col(AgentTemplateSkill.template_id) == template_id
            )
            return set(session.exec(query).all())

    def get_required_skill_ids_for_templates(
        self, template_ids: list[UUID]
    ) -> dict[UUID, set[UUID]]:
        if not template_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = select(AgentTemplateSkill).where(
                col(AgentTemplateSkill.template_id).in_(template_ids)
            )
            result: dict[UUID, set[UUID]] = {}
            for row in session.exec(query).all():
                result.setdefault(row.template_id, set()).add(row.skill_id)
            return result

    def is_skill_required_by_any_template(self, skill_id: UUID) -> bool:
        with Session(self.delegate.engine) as session:
            query = select(AgentTemplateSkill).where(
                col(AgentTemplateSkill.skill_id) == skill_id
            )
            return session.exec(query).first() is not None

    def get_required_skills_for_templates(
        self, template_ids: list[UUID]
    ) -> dict[UUID, list[Skill]]:
        if not template_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentTemplateSkill, Skill)
                .join(Skill, col(AgentTemplateSkill.skill_id) == col(Skill.id))
                .where(col(AgentTemplateSkill.template_id).in_(template_ids))
            )
            result: dict[UUID, list[Skill]] = {}
            for ats, skill in session.exec(query).all():
                result.setdefault(ats.template_id, []).append(skill)
            return result

    def get_template_ids_for_slug_versions(
        self, org_id: UUID, slug_versions: list[tuple[str, int]]
    ) -> dict[tuple[str, int], UUID]:
        if not slug_versions:
            return {}
        with Session(self.delegate.engine) as session:
            result: dict[tuple[str, int], UUID] = {}
            for slug, version in slug_versions:
                row = session.exec(
                    select(AgentTemplate.id)
                    .where(col(AgentTemplate.organization_id) == org_id)
                    .where(col(AgentTemplate.template_slug) == slug)
                    .where(col(AgentTemplate.version) == version)
                ).first()
                if row is not None:
                    result[(slug, version)] = row
            return result
