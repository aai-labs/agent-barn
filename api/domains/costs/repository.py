from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.costs.models import AgentCostSnapshot
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class CostRepository:
    delegate: PostgresRepositoryDelegate

    def save_snapshot(self, snapshot: AgentCostSnapshot) -> AgentCostSnapshot:
        self.delegate.save(snapshot)
        return snapshot

    def find_snapshots_for_org(self, org_id: UUID) -> list[AgentCostSnapshot]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentCostSnapshot)
                .where(col(AgentCostSnapshot.organization_id) == org_id)
                .order_by(col(AgentCostSnapshot.snapshotted_at).desc())
            )
            return list(session.exec(query))

    def find_snapshots_for_agent(self, agent_id: UUID) -> list[AgentCostSnapshot]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentCostSnapshot)
                .where(col(AgentCostSnapshot.agent_id) == agent_id)
                .order_by(col(AgentCostSnapshot.snapshotted_at).desc())
            )
            return list(session.exec(query))
