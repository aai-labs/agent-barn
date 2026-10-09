"""Per-Agent intent and the last explicitly provisioned integration generation."""

from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.domains.agents.models import SecretProvider
from api.infrastructure.postgres.models import BaseModel


class AgentIntegrationIsolation(BaseModel, table=True):
    __tablename__: str = "agent_integration_isolation"
    __table_args__ = (sa.UniqueConstraint("agent_id", "provider", "source", name="uq_agent_integration_isolation"),)

    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE")
    provider: SecretProvider = SqlField(sa_column=Column(sa.String(50), nullable=False))
    isolated: bool = SqlField(nullable=False)
    source: str = SqlField(default="agent_secret", max_length=30)


class AgentIntegrationRuntime(BaseModel, table=True):
    __tablename__: str = "agent_integration_runtime"
    __table_args__ = (sa.UniqueConstraint("agent_id", name="uq_agent_integration_runtime"),)

    agent_id: UUID = SqlField(foreign_key="agent.id", nullable=False, ondelete="CASCADE")
    generation: UUID = SqlField(nullable=False)
    state: str = SqlField(nullable=False)
    # Snapshot keys are provider values, values are {isolated, binding_id}; never credentials.
    bindings: dict = SqlField(default_factory=dict, sa_column=Column(sa.JSON, nullable=False))
    previous_bindings: dict = SqlField(default_factory=dict, sa_column=Column(sa.JSON, nullable=False))

    @property
    def authentication_complete(self) -> bool:
        sharepoint = self.bindings.get("sharepoint", {})
        return not sharepoint.get("isolated") or bool(sharepoint.get("handoff_complete"))
