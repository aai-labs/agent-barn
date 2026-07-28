from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import func
from sqlmodel import Session, col, delete, or_, select

from api.domains.agents.models import Agent, AgentSkill, AgentTemplateSkill
from api.domains.templates.models import AgentTemplate
from api.domains.skills.models import Skill, SkillFilter, SkillSource
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import Pagination


@inject
@singleton
@dataclass
class SkillRepository:
    delegate: PostgresRepositoryDelegate

    def get_by_id(self, skill_id: UUID) -> Skill | None:
        return self.delegate.find_by_id(Skill, skill_id)

    def get_aai_cli_skills(self) -> list[Skill]:
        with Session(self.delegate.engine) as session:
            query = select(Skill).where(col(Skill.source) == SkillSource.AAI_CLI)
            return list(session.exec(query).all())

    def get_by_name_global(self, name: str) -> Skill | None:
        """Find a global (org_id=None) skill by name — used for seeder dedup."""
        with Session(self.delegate.engine) as session:
            query = select(Skill).where(col(Skill.name) == name).where(col(Skill.organization_id).is_(None))
            return session.exec(query).first()

    def find_accessible_for_org(self, org_id: UUID) -> list[Skill]:
        """Return all org-scoped + global skills without filtering or pagination."""
        with Session(self.delegate.engine) as session:
            query = select(Skill).where(
                or_(
                    col(Skill.organization_id) == org_id,
                    col(Skill.organization_id).is_(None),
                )
            )
            return list(session.exec(query).all())

    def find_all_for_org(
        self,
        org_id: UUID,
        skill_filter: SkillFilter,
        pagination: Pagination,
    ) -> tuple[list[Skill], int]:
        """Return org-scoped skills + global AAI_CLI skills, filtered and paginated."""
        with Session(self.delegate.engine) as session:
            conditions = [
                or_(
                    col(Skill.organization_id) == org_id,
                    col(Skill.organization_id).is_(None),
                )
            ]
            if skill_filter.search:
                conditions.append(col(Skill.name).ilike(f"%{skill_filter.search}%"))
            if skill_filter.source is not None:
                conditions.append(col(Skill.source) == skill_filter.source)

            count_query = select(func.count()).select_from(Skill)
            for condition in conditions:
                count_query = count_query.where(condition)
            total = session.scalar(count_query) or 0

            query = select(Skill)
            for condition in conditions:
                query = query.where(condition)
            query = (
                query.order_by(col(Skill.created_at).asc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            )
            return list(session.exec(query).all()), total

    def save(self, skill: Skill) -> Skill:
        self.delegate.save(skill)
        return skill

    def delete(self, skill: Skill) -> None:
        self.delegate.delete(skill)

    def is_assigned_to_any_agent(self, skill_id: UUID) -> bool:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentSkill)
                .join(Agent, col(AgentSkill.agent_id) == col(Agent.id))
                .where(col(AgentSkill.skill_id) == skill_id)
                .where(col(Agent.deleted_at).is_(None))
            )
            return session.exec(query).first() is not None

    def get_latest_template_slugs_requiring_skill(self, skill_id: UUID, org_id: UUID) -> list[str]:
        """Return template slugs whose *latest* version lists this skill as required.

        Considers both org-scoped templates and global predefined templates, so a
        skill required by a global predefined template blocks deletion in every
        org that can see it.
        """
        with Session(self.delegate.engine) as session:
            latest = (
                select(AgentTemplate.id)
                .distinct(col(AgentTemplate.template_slug))
                .where(
                    or_(
                        col(AgentTemplate.organization_id) == org_id,
                        col(AgentTemplate.organization_id).is_(None),
                    )
                )
                .order_by(
                    col(AgentTemplate.template_slug).asc(),
                    col(AgentTemplate.version).desc(),
                )
                .subquery()
            )
            query = (
                select(AgentTemplate.template_slug)
                .join(
                    AgentTemplateSkill,
                    col(AgentTemplate.id) == col(AgentTemplateSkill.template_id),
                )
                .where(col(AgentTemplate.id).in_(select(latest.c.id)))
                .where(col(AgentTemplateSkill.skill_id) == skill_id)
            )
            return list(session.exec(query).all())

    def delete_stale_template_skill_refs(self, skill_id: UUID, org_id: UUID) -> None:
        """Delete agent_template_skill rows for non-latest template versions.

        When deletion is allowed (latest version no longer requires the skill),
        historical join rows from superseded versions must be removed first to
        satisfy the RESTRICT FK constraint on skill.id. Considers org-scoped and
        global predefined templates together.
        """
        with Session(self.delegate.engine) as session:
            latest = (
                select(AgentTemplate.id)
                .distinct(col(AgentTemplate.template_slug))
                .where(
                    or_(
                        col(AgentTemplate.organization_id) == org_id,
                        col(AgentTemplate.organization_id).is_(None),
                    )
                )
                .order_by(
                    col(AgentTemplate.template_slug).asc(),
                    col(AgentTemplate.version).desc(),
                )
                .subquery()
            )
            stmt = (
                delete(AgentTemplateSkill)
                .where(col(AgentTemplateSkill.skill_id) == skill_id)
                .where(col(AgentTemplateSkill.template_id).not_in(select(latest.c.id)))
            )
            session.exec(stmt)  # type: ignore[call-overload]
            session.commit()

    def get_agent_skills_with_details(self, agent_id: UUID) -> list[tuple[AgentSkill, Skill]]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentSkill, Skill)
                .join(Skill, col(AgentSkill.skill_id) == col(Skill.id))
                .where(col(AgentSkill.agent_id) == agent_id)
            )
            return list(session.exec(query).all())

    def get_many_by_ids(self, skill_ids: list[UUID]) -> list[Skill]:
        return self.delegate.find_many(Skill, skill_ids)

    def get_skills_for_agents(self, agent_ids: list[UUID]) -> dict[UUID, list[Skill]]:
        if not agent_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentSkill, Skill)
                .join(Skill, col(AgentSkill.skill_id) == col(Skill.id))
                .where(col(AgentSkill.agent_id).in_(agent_ids))
            )
            result: dict[UUID, list[Skill]] = {}
            for agent_skill, skill in session.exec(query).all():
                result.setdefault(agent_skill.agent_id, []).append(skill)
            return result
