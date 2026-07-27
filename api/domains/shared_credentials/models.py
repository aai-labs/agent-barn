from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from sqlmodel import Column, Field as SqlField

from api.domains.agents.models import SecretProvider
from api.infrastructure.postgres.models import BaseModel


SHARED_CREDENTIAL_ALLOWED_PROVIDERS: frozenset[SecretProvider] = frozenset(
    {
        SecretProvider.GITHUB,
        SecretProvider.JIRA,
        SecretProvider.CONFLUENCE,
        SecretProvider.BITBUCKET,
        SecretProvider.ZOHO_MAIL,
    }
)


class SharedCredential(BaseModel, table=True):
    __tablename__: str = "shared_credential"

    __table_args__ = (
        sa.Index("ix_shared_credential_organization_id", "organization_id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_shared_credential_org_name"),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    provider: SecretProvider = SqlField(sa_column=Column(sa.String(), nullable=False))
    name: str = SqlField(nullable=False, max_length=255)
    content: str = SqlField(sa_column=Column(sa.Text(), nullable=False))  # Fernet-encrypted JSON blob
    created_by: UUID | None = SqlField(default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL")


class SharedCredentialCreate(PydanticBaseModel):
    provider: SecretProvider
    name: str = Field(min_length=1, max_length=255)
    content: dict


class SharedCredentialUpdate(PydanticBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    content: dict | None = None


class SharedCredentialRead(PydanticBaseModel):
    id: UUID
    organization_id: UUID
    provider: SecretProvider
    name: str
    created_by: UUID | None
    agent_count: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SharedCredentialBrief(PydanticBaseModel):
    id: UUID
    provider: SecretProvider
    name: str

    model_config = ConfigDict(from_attributes=True)


class SharedCredentialFilter(PydanticBaseModel):
    search: str | None = None
    provider: SecretProvider | None = None


def get_shared_credential_filter(
    search: str | None = Query(default=None),
    provider: SecretProvider | None = Query(default=None),
) -> SharedCredentialFilter:
    return SharedCredentialFilter(search=search, provider=provider)
