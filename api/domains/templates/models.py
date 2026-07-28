import enum
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, model_validator
from sqlmodel import Column, Field as SqlField

from api.domains.skills.models import SkillRead
from api.infrastructure.postgres.models import BaseModel


class TemplateSource(str, enum.Enum):
    PRE_DEFINED = "pre-defined"
    CUSTOM = "custom"


class AgentTemplate(BaseModel, table=True):
    __tablename__: str = "agent_template"

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


class TemplateRequiredSkillRead(SkillRead):
    # None for a standalone (AND-required) skill; otherwise the key of the
    # "at least one of" group this skill belongs to on this template.
    group_key: str | None = None


class TemplateSkillGroup(PydanticBaseModel):
    """An "at least one of" requirement group: the agent must be assigned at
    least one skill from `skill_ids` at creation, and cannot drop below one
    thereafter."""

    group_key: str = Field(min_length=1, max_length=100)
    skill_ids: list[UUID] = Field(min_length=1)


def _validate_no_skill_overlap(standalone_ids: list[UUID], groups: list[TemplateSkillGroup]) -> None:
    seen_group_keys: set[str] = set()
    seen_in_groups: set[UUID] = set()
    for group in groups:
        if group.group_key in seen_group_keys:
            raise ValueError(f"Duplicate required-skill group_key: {group.group_key}")
        seen_group_keys.add(group.group_key)
        for skill_id in group.skill_ids:
            if skill_id in seen_in_groups:
                raise ValueError(f"Skill {skill_id} cannot belong to more than one required-skill group")
            seen_in_groups.add(skill_id)
    overlap = set(standalone_ids) & seen_in_groups
    if overlap:
        raise ValueError(
            f"Skills cannot be both standalone required and part of a group: {sorted(str(s) for s in overlap)}"
        )


class TemplateRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    template_slug: str
    template_name: str
    template_source: TemplateSource
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
    required_skills: list[TemplateRequiredSkillRead] = Field(default_factory=list)
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
    required_skill_groups: list[TemplateSkillGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_skill_groups(self) -> "TemplateCreate":
        _validate_no_skill_overlap(self.required_skill_ids, self.required_skill_groups)
        return self


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
    required_skill_groups: list[TemplateSkillGroup] | None = None

    @model_validator(mode="after")
    def validate_not_empty(self) -> "TemplateUpdate":
        if not self.model_fields_set:
            raise ValueError("At least one field must be provided")
        return self

    @model_validator(mode="after")
    def validate_skill_groups(self) -> "TemplateUpdate":
        # Only cross-validate the two fields when both are explicitly provided
        # together in this request; when one is omitted it inherits from the
        # prior version, so the service layer re-checks the resolved overlap.
        if self.required_skill_ids is not None and self.required_skill_groups is not None:
            _validate_no_skill_overlap(self.required_skill_ids, self.required_skill_groups)
        return self


class TemplateFilter(PydanticBaseModel):
    search: str | None = None
    source: TemplateSource | None = None


def get_template_filter(
    search: str | None = Query(default=None),
    source: TemplateSource | None = Query(default=None),
) -> TemplateFilter:
    return TemplateFilter(search=search, source=source)
