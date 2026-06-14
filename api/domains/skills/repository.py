from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, col, or_, select

from api.domains.agents.models import AgentSkill
from api.domains.skills.models import Skill, SkillSource
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


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
            query = (
                select(Skill)
                .where(col(Skill.name) == name)
                .where(col(Skill.organization_id).is_(None))
            )
            return session.exec(query).first()

    def find_all_for_org(self, org_id: UUID) -> list[Skill]:
        """Return org-scoped skills + global AAI_CLI skills, ordered by creation time."""
        with Session(self.delegate.engine) as session:
            query = (
                select(Skill)
                .where(
                    or_(
                        col(Skill.organization_id) == org_id,
                        col(Skill.organization_id).is_(None),
                    )
                )
                .order_by(col(Skill.created_at).asc())
            )
            return list(session.exec(query).all())

    def save(self, skill: Skill) -> Skill:
        self.delegate.save(skill)
        return skill

    def delete(self, skill: Skill) -> None:
        self.delegate.delete(skill)

    def is_assigned_to_any_agent(self, skill_id: UUID) -> bool:
        with Session(self.delegate.engine) as session:
            query = select(AgentSkill).where(col(AgentSkill.skill_id) == skill_id)
            return session.exec(query).first() is not None

    def get_agent_skills_with_details(
        self, agent_id: UUID
    ) -> list[tuple[AgentSkill, Skill]]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentSkill, Skill)
                .join(Skill, col(AgentSkill.skill_id) == col(Skill.id))
                .where(col(AgentSkill.agent_id) == agent_id)
            )
            return list(session.exec(query).all())

    def get_many_by_ids(self, skill_ids: list[UUID]) -> list[Skill]:
        return self.delegate.find_many(Skill, skill_ids)
