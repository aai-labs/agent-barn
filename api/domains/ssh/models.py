from datetime import datetime
from typing import Literal, Self
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as DTO
from pydantic import ConfigDict, Field, field_validator, model_validator
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.domains.ssh.keys import normalize_public_key
from api.infrastructure.postgres.models import BaseModel


class SshCredential(BaseModel, table=True):
    __tablename__: str = "ssh_credential"
    __table_args__ = (
        sa.UniqueConstraint("id", "organization_id", name="uq_ssh_credential_tenant"),
        sa.UniqueConstraint("organization_id", "fingerprint", name="uq_ssh_credential_fingerprint"),
        sa.UniqueConstraint("organization_id", "name", name="uq_ssh_credential_name"),
        sa.CheckConstraint("mode IN ('restricted', 'unrestricted')", name="ck_ssh_credential_mode"),
        sa.CheckConstraint("origin IN ('import', 'generate')", name="ck_ssh_credential_origin"),
        sa.CheckConstraint("revision > 0", name="ck_ssh_credential_revision"),
    )
    organization_id: UUID = SqlField(foreign_key="organization.id", ondelete="CASCADE", index=True)
    name: str = SqlField(max_length=120)
    private_key_encrypted: str = SqlField(repr=False)
    public_key: str
    fingerprint: str = SqlField(max_length=100)
    algorithm: str = SqlField(max_length=40)
    origin: str = SqlField(max_length=20)
    enabled: bool = True
    mode: str = SqlField(default="restricted", max_length=20)
    servers: list[dict] = SqlField(default_factory=list, sa_column=Column(sa.JSON, nullable=False))
    revision: int = 1
    created_by: UUID | None = SqlField(default=None, foreign_key="user.id", ondelete="SET NULL")


class AgentSshCredential(BaseModel, table=True):
    __tablename__: str = "agent_ssh_credential"
    __table_args__ = (
        sa.UniqueConstraint("agent_id", "credential_id", name="uq_agent_ssh_credential"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"], ["agent.id", "agent.organization_id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["credential_id", "organization_id"],
            ["ssh_credential.id", "ssh_credential.organization_id"],
            ondelete="RESTRICT",
        ),
    )
    organization_id: UUID = SqlField(index=True)
    agent_id: UUID = SqlField(index=True)
    credential_id: UUID = SqlField(index=True)


class SshRuntimeCredential(BaseModel, table=True):
    __tablename__: str = "ssh_runtime_credential"
    __table_args__ = (
        sa.UniqueConstraint("agent_id", name="uq_ssh_runtime_agent"),
        sa.UniqueConstraint("token_hash", name="uq_ssh_runtime_token"),
        sa.ForeignKeyConstraint(
            ["agent_id", "organization_id"], ["agent.id", "agent.organization_id"], ondelete="CASCADE"
        ),
    )
    organization_id: UUID
    agent_id: UUID
    revision: int = 0
    token_hash: str | None = SqlField(default=None, max_length=64, repr=False)
    generation: UUID | None = None
    applied: list[dict] = SqlField(default_factory=list, sa_column=Column(sa.JSON, nullable=False))
    revoked_at: datetime | None = SqlField(default=None, sa_column=Column(sa.DateTime(timezone=True), nullable=True))


class SshServer(DTO):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9][a-z0-9-]*$")
    hostname: str = Field(min_length=1, max_length=253, pattern=r"^(?:[a-zA-Z0-9][a-zA-Z0-9.:-]*|::[a-fA-F0-9:]*)$")
    port: int = Field(default=22, ge=1, le=65535)
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_][a-zA-Z0-9_.-]*$")
    host_keys: list[str] = Field(min_length=1, max_length=8)

    @field_validator("host_keys")
    @classmethod
    def validate_host_keys(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(normalize_public_key(value) for value in values))


class SshPolicy(DTO):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["restricted", "unrestricted"] = "restricted"
    servers: list[SshServer] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def unique_names(self) -> Self:
        if len({s.name for s in self.servers}) != len(self.servers):
            raise ValueError("Server names must be unique within a credential")
        return self


class SshCredentialCreate(SshPolicy):
    name: str = Field(min_length=1, max_length=120)
    source: Literal["import", "generate"]
    private_key: str | None = Field(default=None, max_length=65536, repr=False)
    passphrase: str | None = Field(default=None, max_length=4096, repr=False)

    @model_validator(mode="after")
    def source_fields(self) -> Self:
        self.name = self.name.strip()
        if not self.name or (self.source == "import" and not self.private_key):
            raise ValueError("Name and imported key are required")
        if self.source == "generate" and (self.private_key is not None or self.passphrase is not None):
            raise ValueError("Generated keys do not accept private material")
        return self


class SshCredentialUpdate(SshPolicy):
    expected_revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=120)
    enabled: bool

    @field_validator("name")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value.strip()


class SshCredentialRead(SshPolicy):
    id: UUID
    name: str
    public_key: str
    fingerprint: str
    algorithm: str
    origin: str
    enabled: bool
    revision: int
    created_at: datetime
    agent_count: int = 0


class SshAssignmentsUpdate(DTO):
    model_config = ConfigDict(extra="forbid")
    credential_ids: list[UUID] = Field(max_length=32)
    expected_revision: int = Field(ge=0)
    restart: bool = False

    @field_validator("credential_ids")
    @classmethod
    def unique_ids(cls, value: list[UUID]) -> list[UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Duplicate SSH credentials")
        return value


class SshAssignmentsRead(DTO):
    credentials: list[SshCredentialRead]
    revision: int
    applied_ids: list[UUID]
    pending_apply: bool
    enabled: bool
    allowed_actions: list[str]
