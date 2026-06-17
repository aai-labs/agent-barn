import enum
from datetime import datetime
from uuid import UUID
import sqlalchemy as sa
from sqlmodel import Column, Field as SqlField
from api.domains.agents.models import SecretProvider
from api.infrastructure.postgres.models import BaseModel
from pydantic import Base64Bytes, BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field


class SkillSource(str, enum.Enum):
    # Predefined skill docs for the baked-in aai-cli tool.
    AAI_CLI = "aai_cli"
    # User-entered skills
    CUSTOM = "custom"


class Skill(BaseModel, table=True):
    __tablename__: str = "skill"

    __table_args__ = (
        sa.Index("ix_skill_organization_id", "organization_id"),
        sa.UniqueConstraint(
            "organization_id", "name", name="uq_skill_organization_name"
        ),
    )

    organization_id: UUID | None = SqlField(
        default=None, foreign_key="organization.id", nullable=True, ondelete="CASCADE"
    )
    name: str = SqlField(nullable=False, max_length=255)
    source: SkillSource = SqlField(sa_column=Column(sa.String(), nullable=False))
    required_providers: list[SecretProvider] = SqlField(
        default_factory=list,
        sa_column=Column(sa.JSON(), nullable=False, server_default="[]"),
    )
    zip_content: bytes = SqlField(sa_column=Column(sa.LargeBinary(), nullable=False))
    tools_pointer: str | None = SqlField(
        default=None, sa_column=Column(sa.Text(), nullable=True)
    )


class SkillCreate(PydanticBaseModel):
    name: str = Field(min_length=1, max_length=255)
    required_providers: list[SecretProvider] = Field(default_factory=list)
    zip_content: Base64Bytes


class SkillUpdate(PydanticBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    required_providers: list[SecretProvider] | None = Field(default=None)
    zip_content: Base64Bytes | None = None


class SkillRead(PydanticBaseModel):
    id: UUID
    organization_id: UUID | None
    name: str
    source: SkillSource
    required_providers: list[SecretProvider]
    tools_pointer: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
