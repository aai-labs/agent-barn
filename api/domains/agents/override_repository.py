from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import func
from sqlmodel import Session, col, delete, select

from api.domains.agents.models import (
    Agent,
    AgentTemplateOverrideDraft,
    AgentTemplateOverrideDraftSkill,
    AgentTemplateOverrideSourceType,
    AgentTemplateOverrideVersion,
    AgentTemplateOverrideVersionSkill,
)
from api.domains.skills.models import Skill
from api.domains.templates.models import AgentTemplate, PlatformTemplate
from api.domains.users.models import User
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

SNAPSHOT_FIELDS: tuple[str, ...] = (
    "source_type",
    "source_template_key",
    "source_template_version",
    "source_platform_template_id",
    "source_agent_template_id",
    "template_name",
    "description",
    "soul_md",
    "identity_md",
    "user_md",
    "tools_md",
    "agents_md",
    "boot_md",
    "bootstrap_md",
    "heartbeat_md",
)


class AgentOverrideConcurrencyError(RuntimeError):
    """Raised when a draft or Agent pin changed after the caller read it."""


@dataclass(frozen=True)
class AgentOverrideSource:
    source_type: AgentTemplateOverrideSourceType
    template_key: str
    version: int
    platform_template_id: UUID | None = None
    agent_template_id: UUID | None = None


@dataclass(frozen=True)
class AgentOverrideSnapshot:
    source: AgentOverrideSource
    template_name: str
    description: str | None
    soul_md: str
    identity_md: str
    user_md: str
    tools_md: str
    agents_md: str
    boot_md: str
    bootstrap_md: str
    heartbeat_md: str
    required_skill_map: Mapping[UUID, str | None]

    @classmethod
    def from_template(
        cls,
        template: AgentTemplate | PlatformTemplate,
        required_skill_map: Mapping[UUID, str | None],
    ) -> AgentOverrideSnapshot:
        if isinstance(template, PlatformTemplate):
            source = AgentOverrideSource(
                source_type=AgentTemplateOverrideSourceType.PLATFORM,
                template_key=template.template_key,
                version=template.version,
                platform_template_id=template.id,
            )
        else:
            source = AgentOverrideSource(
                source_type=AgentTemplateOverrideSourceType.ORGANIZATION,
                template_key=template.template_key,
                version=template.version,
                agent_template_id=template.id,
            )
        return cls(
            source=source,
            template_name=template.template_name,
            description=template.description,
            soul_md=template.soul_md,
            identity_md=template.identity_md,
            user_md=template.user_md,
            tools_md=template.tools_md,
            agents_md=template.agents_md,
            boot_md=template.boot_md,
            bootstrap_md=template.bootstrap_md,
            heartbeat_md=template.heartbeat_md,
            required_skill_map=required_skill_map,
        )

    @classmethod
    def from_override_version(
        cls,
        version: AgentTemplateOverrideVersion,
        required_skill_map: Mapping[UUID, str | None],
    ) -> AgentOverrideSnapshot:
        return cls(
            source=AgentOverrideSource(
                source_type=version.source_type,
                template_key=version.source_template_key,
                version=version.source_template_version,
                platform_template_id=version.source_platform_template_id,
                agent_template_id=version.source_agent_template_id,
            ),
            template_name=version.template_name,
            description=version.description,
            soul_md=version.soul_md,
            identity_md=version.identity_md,
            user_md=version.user_md,
            tools_md=version.tools_md,
            agents_md=version.agents_md,
            boot_md=version.boot_md,
            bootstrap_md=version.bootstrap_md,
            heartbeat_md=version.heartbeat_md,
            required_skill_map=required_skill_map,
        )

    def model_values(self) -> dict[str, Any]:
        return {
            "source_type": self.source.source_type,
            "source_template_key": self.source.template_key,
            "source_template_version": self.source.version,
            "source_platform_template_id": self.source.platform_template_id,
            "source_agent_template_id": self.source.agent_template_id,
            "template_name": self.template_name,
            "description": self.description,
            "soul_md": self.soul_md,
            "identity_md": self.identity_md,
            "user_md": self.user_md,
            "tools_md": self.tools_md,
            "agents_md": self.agents_md,
            "boot_md": self.boot_md,
            "bootstrap_md": self.bootstrap_md,
            "heartbeat_md": self.heartbeat_md,
        }


@inject
@singleton
class AgentOverrideRepository:
    def __init__(self, delegate: PostgresRepositoryDelegate):
        self.delegate = delegate

    def get_draft(self, agent_id: UUID, organization_id: UUID) -> AgentTemplateOverrideDraft | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentTemplateOverrideDraft).where(
                    col(AgentTemplateOverrideDraft.agent_id) == agent_id,
                    col(AgentTemplateOverrideDraft.organization_id) == organization_id,
                )
            ).first()

    def get_versions(self, agent_id: UUID, organization_id: UUID) -> list[AgentTemplateOverrideVersion]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(AgentTemplateOverrideVersion)
                    .where(
                        col(AgentTemplateOverrideVersion.agent_id) == agent_id,
                        col(AgentTemplateOverrideVersion.organization_id) == organization_id,
                    )
                    .order_by(col(AgentTemplateOverrideVersion.version).desc())
                ).all()
            )

    def get_version(self, agent_id: UUID, organization_id: UUID, version: int) -> AgentTemplateOverrideVersion | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentTemplateOverrideVersion).where(
                    col(AgentTemplateOverrideVersion.agent_id) == agent_id,
                    col(AgentTemplateOverrideVersion.organization_id) == organization_id,
                    col(AgentTemplateOverrideVersion.version) == version,
                )
            ).first()

    def get_version_by_id(
        self,
        agent_id: UUID,
        organization_id: UUID,
        version_id: UUID,
    ) -> AgentTemplateOverrideVersion | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentTemplateOverrideVersion).where(
                    col(AgentTemplateOverrideVersion.id) == version_id,
                    col(AgentTemplateOverrideVersion.agent_id) == agent_id,
                    col(AgentTemplateOverrideVersion.organization_id) == organization_id,
                )
            ).first()

    def get_draft_skill_map(self, draft_id: UUID) -> dict[UUID, str | None]:
        with Session(self.delegate.engine) as session:
            return dict(
                session.exec(
                    select(
                        AgentTemplateOverrideDraftSkill.skill_id,
                        AgentTemplateOverrideDraftSkill.group_key,
                    ).where(col(AgentTemplateOverrideDraftSkill.draft_id) == draft_id)
                ).all()
            )

    def get_draft_skill_map_for_agent(
        self,
        agent_id: UUID,
        organization_id: UUID,
    ) -> dict[UUID, str | None]:
        with Session(self.delegate.engine) as session:
            draft_id = session.exec(
                select(AgentTemplateOverrideDraft.id).where(
                    col(AgentTemplateOverrideDraft.agent_id) == agent_id,
                    col(AgentTemplateOverrideDraft.organization_id) == organization_id,
                )
            ).first()
        return self.get_draft_skill_map(draft_id) if draft_id is not None else {}

    def get_version_skill_map(self, version_id: UUID) -> dict[UUID, str | None]:
        with Session(self.delegate.engine) as session:
            return dict(
                session.exec(
                    select(
                        AgentTemplateOverrideVersionSkill.skill_id,
                        AgentTemplateOverrideVersionSkill.group_key,
                    ).where(col(AgentTemplateOverrideVersionSkill.version_id) == version_id)
                ).all()
            )

    def get_skills_for_draft(self, draft_id: UUID) -> list[tuple[Skill, str | None]]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(Skill, AgentTemplateOverrideDraftSkill.group_key)
                    .join(
                        AgentTemplateOverrideDraftSkill,
                        col(AgentTemplateOverrideDraftSkill.skill_id) == col(Skill.id),
                    )
                    .where(col(AgentTemplateOverrideDraftSkill.draft_id) == draft_id)
                    .order_by(col(AgentTemplateOverrideDraftSkill.group_key).nulls_first(), col(Skill.name))
                ).all()
            )

    def get_skills_for_version(self, version_id: UUID) -> list[tuple[Skill, str | None]]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(Skill, AgentTemplateOverrideVersionSkill.group_key)
                    .join(
                        AgentTemplateOverrideVersionSkill,
                        col(AgentTemplateOverrideVersionSkill.skill_id) == col(Skill.id),
                    )
                    .where(col(AgentTemplateOverrideVersionSkill.version_id) == version_id)
                    .order_by(col(AgentTemplateOverrideVersionSkill.group_key).nulls_first(), col(Skill.name))
                ).all()
            )

    def get_author(self, user_id: UUID | None) -> User | None:
        if user_id is None:
            return None
        with Session(self.delegate.engine) as session:
            return session.get(User, user_id)

    def create_draft(
        self,
        draft: AgentTemplateOverrideDraft,
        snapshot: AgentOverrideSnapshot,
        *,
        expected_pin_type: str,
        expected_pin_id: UUID,
    ) -> AgentTemplateOverrideDraft:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            agent = self._lock_agent(session, draft.agent_id, draft.organization_id)
            if agent is None:
                raise ValueError("Agent not found")
            existing = session.exec(
                select(AgentTemplateOverrideDraft)
                .where(
                    col(AgentTemplateOverrideDraft.agent_id) == draft.agent_id,
                    col(AgentTemplateOverrideDraft.organization_id) == draft.organization_id,
                )
                .with_for_update()
            ).first()
            if existing is not None:
                return existing
            if not self._pin_matches(agent, expected_pin_type, expected_pin_id):
                raise AgentOverrideConcurrencyError("The Agent's active Template changed; reload and try again")

            session.add(draft)
            session.flush()
            self._replace_draft_skills(session, draft.id, snapshot.required_skill_map)
            session.commit()
            session.refresh(draft)
            return draft

    def update_draft(
        self,
        agent_id: UUID,
        organization_id: UUID,
        updates: Mapping[str, object],
        skill_map: Mapping[UUID, str | None] | None,
        *,
        expected_updated_at: datetime,
    ) -> AgentTemplateOverrideDraft:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            agent = self._lock_agent(session, agent_id, organization_id)
            if agent is None:
                raise ValueError("Agent not found")
            draft = session.exec(
                select(AgentTemplateOverrideDraft)
                .where(
                    col(AgentTemplateOverrideDraft.agent_id) == agent_id,
                    col(AgentTemplateOverrideDraft.organization_id) == organization_id,
                )
                .with_for_update()
            ).first()
            if draft is None:
                raise ValueError("Draft not found")
            self._check_timestamp(draft.updated_at, expected_updated_at)
            for field, value in updates.items():
                if field in SNAPSHOT_FIELDS:
                    setattr(draft, field, value)
            session.add(draft)
            if skill_map is not None:
                self._replace_draft_skills(session, draft.id, skill_map)
            session.commit()
            session.refresh(draft)
            return draft

    def publish_draft(
        self,
        agent_id: UUID,
        organization_id: UUID,
        *,
        actor_user_id: UUID,
        expected_updated_at: datetime,
    ) -> AgentTemplateOverrideVersion:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            agent = self._lock_agent(session, agent_id, organization_id)
            if agent is None:
                raise ValueError("Agent not found")
            draft = session.exec(
                select(AgentTemplateOverrideDraft)
                .where(
                    col(AgentTemplateOverrideDraft.agent_id) == agent_id,
                    col(AgentTemplateOverrideDraft.organization_id) == organization_id,
                )
                .with_for_update()
            ).first()
            if draft is None:
                raise ValueError("Draft not found")
            self._check_timestamp(draft.updated_at, expected_updated_at)
            next_version = (
                session.exec(
                    select(func.max(col(AgentTemplateOverrideVersion.version))).where(
                        col(AgentTemplateOverrideVersion.agent_id) == agent_id,
                        col(AgentTemplateOverrideVersion.organization_id) == organization_id,
                    )
                ).one()
                or 0
            ) + 1
            published = AgentTemplateOverrideVersion(
                organization_id=organization_id,
                agent_id=agent_id,
                version=next_version,
                created_by_user_id=actor_user_id,
                **{field: getattr(draft, field) for field in SNAPSHOT_FIELDS},
            )
            session.add(published)
            session.flush()
            draft_skills = session.exec(
                select(AgentTemplateOverrideDraftSkill).where(col(AgentTemplateOverrideDraftSkill.draft_id) == draft.id)
            ).all()
            session.add_all(
                [
                    AgentTemplateOverrideVersionSkill(
                        version_id=published.id,
                        skill_id=row.skill_id,
                        group_key=row.group_key,
                    )
                    for row in draft_skills
                ]
            )
            session.delete(draft)
            session.commit()
            session.refresh(published)
            return published

    def select_pin(
        self,
        agent_id: UUID,
        organization_id: UUID,
        *,
        selection_type: str,
        selected_id: UUID,
        expected_agent_updated_at: datetime,
    ) -> Agent:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            agent = self._lock_agent(session, agent_id, organization_id)
            if agent is None:
                raise ValueError("Agent not found")
            self._check_timestamp(agent.updated_at, expected_agent_updated_at)
            agent.platform_template_id = selected_id if selection_type == "platform" else None
            agent.agent_template_id = selected_id if selection_type == "organization" else None
            agent.agent_template_override_version_id = selected_id if selection_type == "override" else None
            session.add(agent)
            session.commit()
            session.refresh(agent)
            return agent

    @staticmethod
    def _lock_agent(session: Session, agent_id: UUID, organization_id: UUID) -> Agent | None:
        return session.exec(
            select(Agent)
            .where(
                col(Agent.id) == agent_id,
                col(Agent.organization_id) == organization_id,
                col(Agent.deleted_at).is_(None),
            )
            .with_for_update()
        ).first()

    @staticmethod
    def _pin_matches(agent: Agent, pin_type: str, pin_id: UUID) -> bool:
        if pin_type == "platform":
            return agent.platform_template_id == pin_id
        if pin_type == "organization":
            return agent.agent_template_id == pin_id
        if pin_type == "override":
            return agent.agent_template_override_version_id == pin_id
        return False

    @staticmethod
    def _check_timestamp(actual: datetime, expected: datetime) -> None:
        if actual != expected:
            raise AgentOverrideConcurrencyError("The resource changed; reload and try again")

    @staticmethod
    def _replace_draft_skills(
        session: Session,
        draft_id: UUID,
        skill_map: Mapping[UUID, str | None],
    ) -> None:
        session.exec(
            delete(AgentTemplateOverrideDraftSkill).where(col(AgentTemplateOverrideDraftSkill.draft_id) == draft_id)
        )
        session.add_all(
            [
                AgentTemplateOverrideDraftSkill(
                    draft_id=draft_id,
                    skill_id=skill_id,
                    group_key=group_key,
                )
                for skill_id, group_key in skill_map.items()
            ]
        )
