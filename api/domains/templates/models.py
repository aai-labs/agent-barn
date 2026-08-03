import enum
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, model_validator
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.domains.skills.models import SkillRead
from api.infrastructure.postgres.models import BaseModel


class TemplateSource(str, enum.Enum):
    PRE_DEFINED = "pre-defined"
    CUSTOM = "custom"


class AgentTemplate(BaseModel, table=True):
    __tablename__: str = "agent_template"

    # agent_template is strictly organization-scoped: custom templates created
    # by an org and org forks of platform predefined templates. Global
    # predefined templates live in platform_template. A fork records its origin
    # via forked_from_platform_template_id so "update available" detection is
    # possible later.
    __table_args__ = (
        sa.Index("ix_agent_template_organization_id", "organization_id"),
        sa.UniqueConstraint(
            "organization_id",
            "template_slug",
            "version",
            name="uq_agent_template_org_slug_version",
        ),
    )

    organization_id: UUID = SqlField(foreign_key="organization.id", nullable=False, ondelete="CASCADE")
    forked_from_platform_template_id: UUID | None = SqlField(
        default=None,
        foreign_key="platform_template.id",
        nullable=True,
        ondelete="SET NULL",
    )
    template_slug: str = SqlField(nullable=False, max_length=255)
    template_name: str = SqlField(nullable=False, max_length=255)
    template_source: TemplateSource = SqlField(
        default=TemplateSource.CUSTOM,
        sa_column=Column(sa.String(20), nullable=False, server_default="custom"),
    )
    version: int = SqlField(nullable=False)
    description: str | None = SqlField(default=None, nullable=True, max_length=500)
    soul_md: str = SqlField(nullable=False)
    identity_md: str = SqlField(nullable=False)
    user_md: str = SqlField(nullable=False)
    tools_md: str = SqlField(nullable=False)
    agents_md: str = SqlField(nullable=False)
    boot_md: str = SqlField(nullable=False)
    bootstrap_md: str = SqlField(nullable=False)
    heartbeat_md: str = SqlField(nullable=False)


class PlatformTemplate(BaseModel, table=True):
    __tablename__: str = "platform_template"

    # Global platform predefined templates. No organization_id — these are
    # platform resources visible to every organization, like built-in aai_cli
    # skills. Always template_source = pre-defined (implicit; not stored).
    __table_args__ = (
        sa.UniqueConstraint(
            "template_slug",
            "version",
            name="uq_platform_template_slug_version",
        ),
    )

    template_slug: str = SqlField(nullable=False, max_length=255)
    template_name: str = SqlField(nullable=False, max_length=255)
    version: int = SqlField(nullable=False)
    description: str | None = SqlField(default=None, nullable=True, max_length=500)
    soul_md: str = SqlField(nullable=False)
    identity_md: str = SqlField(nullable=False)
    user_md: str = SqlField(nullable=False)
    tools_md: str = SqlField(nullable=False)
    agents_md: str = SqlField(nullable=False)
    boot_md: str = SqlField(nullable=False)
    bootstrap_md: str = SqlField(nullable=False)
    heartbeat_md: str = SqlField(nullable=False)


class TemplateRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID | None
    template_slug: str
    template_name: str
    template_source: TemplateSource
    # Set only for org forks of a platform predefined template; NULL for custom
    # templates and for platform templates themselves.
    forked_from_platform_template_id: UUID | None = None
    version: int
    description: str | None
    soul_md: str
    identity_md: str
    user_md: str
    tools_md: str
    agents_md: str
    boot_md: str
    bootstrap_md: str
    heartbeat_md: str
    created_at: datetime
    updated_at: datetime
    required_skills: list[SkillRead] = Field(default_factory=list)
    in_use: bool = False


class TemplateCreate(PydanticBaseModel):
    template_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    soul_md: str | None = None
    identity_md: str | None = None
    user_md: str | None = None
    tools_md: str | None = None
    agents_md: str | None = None
    boot_md: str | None = None
    bootstrap_md: str | None = None
    heartbeat_md: str | None = None
    required_skill_ids: list[UUID] = Field(default_factory=list)


class TemplateUpdate(PydanticBaseModel):
    # template_name is intentionally NOT editable: new versions inherit the v1
    # name. Only the markdown content and description can change between versions.
    description: str | None = None
    soul_md: str | None = None
    identity_md: str | None = None
    user_md: str | None = None
    tools_md: str | None = None
    agents_md: str | None = None
    boot_md: str | None = None
    bootstrap_md: str | None = None
    heartbeat_md: str | None = None
    required_skill_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def validate_not_empty(self) -> TemplateUpdate:
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self


class TemplateFilter(PydanticBaseModel):
    search: str | None = None
    source: TemplateSource | None = None


def get_template_filter(
    search: str | None = Query(default=None),
    source: TemplateSource | None = Query(default=None),
) -> TemplateFilter:
    return TemplateFilter(search=search, source=source)
