from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import func
from sqlmodel import Session, col, select

from api.domains.agents.models import (
    Agent,
    AgentFilter,
    AgentLogSnapshot,
    AgentSecret,
    AgentSkill,
    AgentSlackConfig,
    AgentTeamsConfig,
    SecretProvider,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import Pagination


@inject
@singleton
@dataclass
class AgentRepository:
    delegate: PostgresRepositoryDelegate

    def get_by_id(self, agent_id: UUID) -> Agent | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(Agent)
                .where(col(Agent.id) == agent_id)
                .where(col(Agent.deleted_at).is_(None))
            )
            return session.exec(query).first()

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
    ) -> tuple[list[Agent], int]:
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

            agents = list(session.exec(query).all())
            return agents, total

    # --- Slack config ---

    def get_slack_config(self, agent_id: UUID) -> AgentSlackConfig | None:
        with Session(self.delegate.engine) as session:
            query = select(AgentSlackConfig).where(
                col(AgentSlackConfig.agent_id) == agent_id
            )
            return session.exec(query).first()

    def save_slack_config(self, config: AgentSlackConfig) -> AgentSlackConfig:
        self.delegate.save(config)
        return config

    def get_slack_configs_for_agents(
        self, agent_ids: list[UUID]
    ) -> dict[UUID, AgentSlackConfig]:
        if not agent_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = select(AgentSlackConfig).where(
                col(AgentSlackConfig.agent_id).in_(agent_ids)
            )
            return {c.agent_id: c for c in session.exec(query).all()}

    # --- Teams config ---

    def get_teams_config(self, agent_id: UUID) -> AgentTeamsConfig | None:
        with Session(self.delegate.engine) as session:
            query = select(AgentTeamsConfig).where(
                col(AgentTeamsConfig.agent_id) == agent_id
            )
            return session.exec(query).first()

    def save_teams_config(self, config: AgentTeamsConfig) -> AgentTeamsConfig:
        self.delegate.save(config)
        return config

    def get_teams_configs_for_agents(
        self, agent_ids: list[UUID]
    ) -> dict[UUID, AgentTeamsConfig]:
        if not agent_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = select(AgentTeamsConfig).where(
                col(AgentTeamsConfig.agent_id).in_(agent_ids)
            )
            return {c.agent_id: c for c in session.exec(query).all()}

    # --- Integration secrets ---

    def save_secret(self, secret: AgentSecret) -> AgentSecret:
        self.delegate.save(secret)
        return secret

    def get_secret(
        self, agent_id: UUID, provider: SecretProvider
    ) -> AgentSecret | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentSecret)
                .where(col(AgentSecret.agent_id) == agent_id)
                .where(col(AgentSecret.provider) == provider)
            )
            return session.exec(query).first()

    def get_secrets_for_agent(self, agent_id: UUID) -> list[AgentSecret]:
        with Session(self.delegate.engine) as session:
            query = select(AgentSecret).where(col(AgentSecret.agent_id) == agent_id)
            return list(session.exec(query).all())

    def get_secrets_for_agents(
        self, agent_ids: list[UUID]
    ) -> dict[UUID, list[AgentSecret]]:
        if not agent_ids:
            return {}
        with Session(self.delegate.engine) as session:
            query = select(AgentSecret).where(col(AgentSecret.agent_id).in_(agent_ids))
            result: dict[UUID, list[AgentSecret]] = {}
            for secret in session.exec(query).all():
                result.setdefault(secret.agent_id, []).append(secret)
            return result

    def delete_secret(self, agent_id: UUID, provider: SecretProvider) -> None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentSecret)
                .where(col(AgentSecret.agent_id) == agent_id)
                .where(col(AgentSecret.provider) == provider)
            )
            secret = session.exec(query).first()
            if secret is not None:
                session.delete(secret)
                session.commit()

    # --- Skills ---

    def save_skills(self, skills: list[AgentSkill]) -> None:
        self.delegate.save_all(skills)

    def add_skill(self, agent_id: UUID, skill_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            existing = session.exec(
                select(AgentSkill)
                .where(col(AgentSkill.agent_id) == agent_id)
                .where(col(AgentSkill.skill_id) == skill_id)
            ).first()
            if existing is None:
                session.add(AgentSkill(agent_id=agent_id, skill_id=skill_id))
                session.commit()

    def remove_skill(self, agent_id: UUID, skill_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(AgentSkill)
                .where(col(AgentSkill.agent_id) == agent_id)
                .where(col(AgentSkill.skill_id) == skill_id)
            ).first()
            if row is not None:
                session.delete(row)
                session.commit()

    def get_skills_for_agent(self, agent_id: UUID) -> list[AgentSkill]:
        with Session(self.delegate.engine) as session:
            query = select(AgentSkill).where(col(AgentSkill.agent_id) == agent_id)
            return list(session.exec(query).all())

    # --- Log snapshots ---

    def save_log_snapshot(self, snapshot: AgentLogSnapshot) -> AgentLogSnapshot:
        self.delegate.save(snapshot)
        return snapshot

    def get_latest_log_snapshot(self, agent_id: UUID) -> AgentLogSnapshot | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentLogSnapshot)
                .where(col(AgentLogSnapshot.agent_id) == agent_id)
                .order_by(col(AgentLogSnapshot.session_ended_at).desc())
                .limit(1)
            )
            return session.exec(query).first()

    def get_snapshot_by_id(
        self, agent_id: UUID, snapshot_id: UUID
    ) -> AgentLogSnapshot | None:
        with Session(self.delegate.engine) as session:
            query = select(AgentLogSnapshot).where(
                col(AgentLogSnapshot.agent_id) == agent_id,
                col(AgentLogSnapshot.id) == snapshot_id,
            )
            return session.exec(query).first()

    def get_previous_snapshot(
        self, agent_id: UUID, before: datetime
    ) -> AgentLogSnapshot | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentLogSnapshot)
                .where(
                    col(AgentLogSnapshot.agent_id) == agent_id,
                    col(AgentLogSnapshot.session_ended_at) < before,
                )
                .order_by(col(AgentLogSnapshot.session_ended_at).desc())
                .limit(1)
            )
            return session.exec(query).first()

    def delete_old_snapshots(self, agent_id: UUID, keep: int) -> None:
        with Session(self.delegate.engine) as session:
            keep_ids_query = (
                select(AgentLogSnapshot.id)
                .where(col(AgentLogSnapshot.agent_id) == agent_id)
                .order_by(col(AgentLogSnapshot.session_ended_at).desc())
                .limit(keep)
            )
            keep_ids = list(session.exec(keep_ids_query).all())
            if not keep_ids:
                return
            old_query = (
                select(AgentLogSnapshot)
                .where(
                    col(AgentLogSnapshot.agent_id) == agent_id,
                    col(AgentLogSnapshot.id).notin_(keep_ids),
                )
            )
            old_snapshots = list(session.exec(old_query).all())
            for snap in old_snapshots:
                session.delete(snap)
            if old_snapshots:
                session.commit()

    def save(self, agent: Agent) -> Agent:
        self.delegate.save(agent)
        return agent
