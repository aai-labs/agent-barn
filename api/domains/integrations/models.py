"""Per-Agent intent and the last explicitly provisioned integration generation."""

from typing import Self
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as DTO
from pydantic import ConfigDict, Field, model_validator
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.domains.agents.models import AgentSecretCreate, AgentSharedCredentialAttach, AgentUpdate, SecretProvider
from api.domains.custom_api.models import CustomApiConnectionsApply
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


class IntegrationPolicyUpdate(DTO):
    model_config = ConfigDict(extra="forbid")
    provider: SecretProvider
    isolated: bool


class AgentIntegrationsApply(DTO):
    model_config = ConfigDict(extra="forbid")

    secrets: list[AgentSecretCreate] = Field(default_factory=list)
    shared_credentials: list[AgentSharedCredentialAttach] = Field(default_factory=list)
    removed_secret_providers: list[SecretProvider] = Field(default_factory=list)
    policies: list[IntegrationPolicyUpdate] = Field(default_factory=list)
    custom_api: CustomApiConnectionsApply = Field(default_factory=CustomApiConnectionsApply)
    restart: bool = False

    def credential_update(self) -> AgentUpdate:
        return AgentUpdate(
            secrets=self.secrets,
            shared_credentials=self.shared_credentials,
            removed_secret_providers=self.removed_secret_providers,
        )

    @model_validator(mode="after")
    def validate_operations(self) -> Self:
        self.credential_update()
        providers = [policy.provider for policy in self.policies]
        if len(providers) != len(set(providers)):
            raise ValueError("Duplicate isolation policy providers are not allowed")
        if self.custom_api.restart or any(create.restart for create in self.custom_api.creates):
            raise ValueError("Use the top-level restart choice")
        return self
