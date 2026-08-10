from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import func
from sqlmodel import Session, col, delete, or_, select

from api.domains.agents.models import Agent, AgentSkill, AgentTemplateSkill, PlatformTemplateSkill
from api.domains.skills.models import Skill, SkillFilter, SkillSource
from api.domains.templates.models import AgentTemplate, PlatformTemplate
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

    def find_all_global(self) -> list[Skill]:
        """Return every global Skill available to platform-owned resources."""
        with Session(self.delegate.engine) as session:
            query = select(Skill).where(col(Skill.organization_id).is_(None)).order_by(col(Skill.name).asc())
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

    def get_latest_template_keys_requiring_skill(self, skill_id: UUID, org_id: UUID) -> list[str]:
        """Return template keys whose *latest* version lists this skill as required.

        Considers org-scoped agent_template versions (custom + forks) and global
        platform_template versions, so a skill required by any template visible
        to the org blocks deletion.
        """
        template_keys: set[str] = set()
        with Session(self.delegate.engine) as session:
            latest_org = (
                select(AgentTemplate.id)
                .distinct(col(AgentTemplate.template_key))
                .where(col(AgentTemplate.organization_id) == org_id)
                .order_by(
                    col(AgentTemplate.template_key).asc(),
                    col(AgentTemplate.version).desc(),
                )
                .subquery()
            )
            org_q = (
                select(AgentTemplate.template_key)
                .join(AgentTemplateSkill, col(AgentTemplate.id) == col(AgentTemplateSkill.template_id))
                .where(col(AgentTemplate.id).in_(select(latest_org.c.id)))
                .where(col(AgentTemplateSkill.skill_id) == skill_id)
            )
            template_keys.update(session.exec(org_q).all())

            latest_platform = (
                select(PlatformTemplate.id)
                .distinct(col(PlatformTemplate.template_key))
                .order_by(
                    col(PlatformTemplate.template_key).asc(),
                    col(PlatformTemplate.version).desc(),
                )
                .subquery()
            )
            platform_q = (
                select(PlatformTemplate.template_key)
                .join(
                    PlatformTemplateSkill,
                    col(PlatformTemplate.id) == col(PlatformTemplateSkill.template_id),
                )
                .where(col(PlatformTemplate.id).in_(select(latest_platform.c.id)))
                .where(col(PlatformTemplateSkill.skill_id) == skill_id)
            )
            template_keys.update(session.exec(platform_q).all())
        return list(template_keys)

    def delete_stale_template_skill_refs(self, skill_id: UUID, org_id: UUID) -> None:
        """Delete template-skill join rows for non-latest template versions.

        When deletion is allowed (latest version no longer requires the skill),
        historical join rows from superseded versions must be removed first to
        satisfy the RESTRICT FK constraint on skill.id. Handles org-scoped
        agent_template versions and global platform_template versions.
        """
        with Session(self.delegate.engine) as session:
            latest_org = (
                select(AgentTemplate.id)
                .distinct(col(AgentTemplate.template_key))
                .where(col(AgentTemplate.organization_id) == org_id)
                .order_by(
                    col(AgentTemplate.template_key).asc(),
                    col(AgentTemplate.version).desc(),
                )
                .subquery()
            )
            session.exec(  # type: ignore[call-overload]
                delete(AgentTemplateSkill)
                .where(col(AgentTemplateSkill.skill_id) == skill_id)
                .where(col(AgentTemplateSkill.template_id).not_in(select(latest_org.c.id)))
            )

            latest_platform = (
                select(PlatformTemplate.id)
                .distinct(col(PlatformTemplate.template_key))
                .order_by(
                    col(PlatformTemplate.template_key).asc(),
                    col(PlatformTemplate.version).desc(),
                )
                .subquery()
            )
            session.exec(  # type: ignore[call-overload]
                delete(PlatformTemplateSkill)
                .where(col(PlatformTemplateSkill.skill_id) == skill_id)
                .where(col(PlatformTemplateSkill.template_id).not_in(select(latest_platform.c.id)))
            )
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
