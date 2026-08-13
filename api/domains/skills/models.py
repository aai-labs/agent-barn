import enum
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field
from sqlmodel import Column
from sqlmodel import Field as SqlField

from api.domains.agents.models import SecretProvider
from api.domains.skills.files import DEFAULT_ENTRY_PATH
from api.infrastructure.postgres.models import BaseModel


class SkillSource(str, enum.Enum):
    # Predefined skill docs for the baked-in aai-cli tool.
    AAI_CLI = "aai_cli"
    # User-entered skills
    CUSTOM = "custom"


class Skill(BaseModel, table=True):
    """A skill lineage: stable identity, name, and mount location.

    Content lives in append-only ``skill_version`` rows rather than on this row, so
    agent-skill and template-skill assignments keep pointing at a lineage instead of
    a frozen snapshot of its prose. The published version is always the highest
    ``version`` for the lineage — rollback publishes a *new* version copied from an
    older one, so history is never mutated and no current-version pointer is needed.
    """

    __tablename__: str = "skill"

    __table_args__ = (
        sa.Index("ix_skill_organization_id", "organization_id"),
        sa.UniqueConstraint("organization_id", "name", name="uq_skill_organization_name"),
        sa.UniqueConstraint("organization_id", "slug", name="uq_skill_organization_slug"),
    )

    organization_id: UUID | None = SqlField(
        default=None, foreign_key="organization.id", nullable=True, ondelete="CASCADE"
    )
    name: str = SqlField(nullable=False, max_length=255)
    # Immutable URL/identity slug. Display name can change without moving files.
    slug: str = SqlField(nullable=False, max_length=255)
    description: str | None = SqlField(default=None, sa_column=Column(sa.Text(), nullable=True))
    # Directory the skill's files are written to under ./skills. Defaults to the slug,
    # but the ten built-ins deliberately share "aai-cli" so their long-published
    # pointer paths (./skills/aai-cli/jira_skill.md) keep resolving.
    root_dir: str = SqlField(nullable=False, max_length=255)
    # Entry-point file, relative to root_dir. Custom skills use SKILL.md; built-ins
    # keep their historical per-provider filenames.
    entry_path: str = SqlField(nullable=False, max_length=512, default=DEFAULT_ENTRY_PATH)
    source: SkillSource = SqlField(sa_column=Column(sa.String(), nullable=False))
    required_providers: list[SecretProvider] = SqlField(
        default_factory=list,
        sa_column=Column(sa.JSON(), nullable=False, server_default="[]"),
    )
    # Superseded by skill_version/skill_file; retained until the follow-up migration
    # drops it so a rollback of this deploy still has content to serve.
    zip_content: bytes | None = SqlField(default=None, sa_column=Column(sa.LargeBinary(), nullable=True))
    # Only an override: when NULL the pointer is derived from name + description +
    # entry path. The built-ins carry curated wording here.
    tools_pointer: str | None = SqlField(default=None, sa_column=Column(sa.Text(), nullable=True))


class SkillVersion(BaseModel, table=True):
    """An immutable, published content snapshot of a skill lineage."""

    __tablename__: str = "skill_version"

    __table_args__ = (
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_version_skill_version"),
        sa.Index("ix_skill_version_skill_id", "skill_id"),
    )

    skill_id: UUID = SqlField(foreign_key="skill.id", nullable=False, ondelete="CASCADE")
    version: int = SqlField(nullable=False)
    created_by: UUID | None = SqlField(default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL")
    # Set when this version was published by restoring an older one, for audit and
    # for the "restored from v2" label in version history.
    restored_from_version: int | None = SqlField(default=None, nullable=True)


class SkillFile(BaseModel, table=True):
    """One text file in a skill version, addressed by a path relative to the skill root.

    Directories are implied by the path and never stored: there is no per-directory
    metadata to keep, and a flat path list cannot drift out of sync with itself.
    """

    __tablename__: str = "skill_file"

    __table_args__ = (
        sa.UniqueConstraint("skill_version_id", "path", name="uq_skill_file_version_path"),
        sa.Index("ix_skill_file_version_id", "skill_version_id"),
    )

    skill_version_id: UUID = SqlField(foreign_key="skill_version.id", nullable=False, ondelete="CASCADE")
    path: str = SqlField(nullable=False, max_length=512)
    content: str = SqlField(sa_column=Column(sa.Text(), nullable=False))


def derive_tools_pointer(skill: Skill) -> str:
    """The line appended to TOOLS.md telling the agent this skill exists.

    Built-ins carry curated wording in ``tools_pointer``; everything else is derived
    from the skill's own metadata, so renaming a skill or editing its description
    can never leave a stale pointer behind.
    """
    if skill.tools_pointer:
        return skill.tools_pointer
    description = f" {skill.description.strip()}" if skill.description else ""
    return f"\nFor {skill.name}:{description} See ./skills/{skill.root_dir}/{skill.entry_path}\n"


class SkillFileInput(PydanticBaseModel):
    path: str = Field(min_length=1, max_length=512)
    content: str


class SkillFileRead(PydanticBaseModel):
    path: str
    content: str

    model_config = ConfigDict(from_attributes=True)


class SkillCreate(PydanticBaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    required_providers: list[SecretProvider] = Field(default_factory=list)
    files: list[SkillFileInput] = Field(min_length=1)


class SkillUpdate(PydanticBaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    required_providers: list[SecretProvider] | None = Field(default=None)
    # Omit to leave content untouched; supplying it publishes the next version.
    files: list[SkillFileInput] | None = Field(default=None, min_length=1)


class SkillRead(PydanticBaseModel):
    """Lineage-level view of a skill, with no version attached.

    Templates require a skill *lineage* rather than a snapshot of it, so
    ``TemplateRequiredSkillRead`` inherits this and deliberately carries no version.
    """

    id: UUID
    organization_id: UUID | None
    name: str
    slug: str
    description: str | None
    root_dir: str
    entry_path: str
    source: SkillSource
    required_providers: list[SecretProvider]
    tools_pointer: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SkillSummaryRead(SkillRead):
    """A skill as the Skills UI sees it: lineage plus its currently published version."""

    version: int


class SkillDetailRead(SkillSummaryRead):
    files: list[SkillFileRead]


class SkillFilter(PydanticBaseModel):
    search: str | None = None
    source: SkillSource | None = None


def get_skill_filter(
    search: str | None = Query(default=None),
    source: SkillSource | None = Query(default=None),
) -> SkillFilter:
    return SkillFilter(search=search, source=source)
