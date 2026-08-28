import enum
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from fastapi import Query
from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field, model_validator
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


class SkillScope(str, enum.Enum):
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    AGENT = "agent"


class Skill(BaseModel, table=True):
    """A skill lineage: stable identity, name, and mount location.

    Content lives in append-only ``skill_version`` rows rather than on this row, so
    agent-skill and template-skill assignments keep pointing at a lineage instead of
    a frozen snapshot of its prose. The published version is always the highest
    ``version`` for the lineage — restoring an older version as a draft and
    publishing it produces a *new* version copied from the older one, so history
    is never mutated and no current-version pointer is needed.
    """

    __tablename__: str = "skill"

    __table_args__ = (
        sa.Index("ix_skill_organization_id", "organization_id"),
        sa.Index("ix_skill_agent_id", "agent_id"),
        sa.Index(
            "uq_skill_platform_name",
            "name",
            unique=True,
            postgresql_where=sa.text("organization_id IS NULL AND agent_id IS NULL"),
        ),
        sa.Index(
            "uq_skill_org_name",
            "organization_id",
            "name",
            unique=True,
            postgresql_where=sa.text("organization_id IS NOT NULL AND agent_id IS NULL"),
        ),
        sa.Index(
            "uq_skill_agent_name",
            "agent_id",
            "name",
            unique=True,
            postgresql_where=sa.text("agent_id IS NOT NULL"),
        ),
        sa.Index(
            "uq_skill_platform_slug",
            "slug",
            unique=True,
            postgresql_where=sa.text("organization_id IS NULL AND agent_id IS NULL"),
        ),
        sa.Index(
            "uq_skill_org_slug",
            "organization_id",
            "slug",
            unique=True,
            postgresql_where=sa.text("organization_id IS NOT NULL AND agent_id IS NULL"),
        ),
        sa.Index(
            "uq_skill_agent_slug",
            "agent_id",
            "slug",
            unique=True,
            postgresql_where=sa.text("agent_id IS NOT NULL"),
        ),
        sa.CheckConstraint(
            "agent_id IS NULL OR organization_id IS NOT NULL",
            name="ck_skill_agent_requires_organization",
        ),
    )

    organization_id: UUID | None = SqlField(
        default=None, foreign_key="organization.id", nullable=True, ondelete="CASCADE"
    )
    # Agent-owned Skills retain their Organization for tenant-scoped queries and
    # point at the Agent that owns the private lineage. Platform Skills have both
    # owner columns NULL; Organization Skills have only organization_id set.
    agent_id: UUID | None = SqlField(default=None, foreign_key="agent.id", nullable=True, ondelete="CASCADE")
    name: str = SqlField(nullable=False, max_length=255)
    # Immutable URL/identity slug. Display name can change without moving files.
    slug: str = SqlField(nullable=False, max_length=255)
    description: str | None = SqlField(default=None, sa_column=Column(sa.Text(), nullable=True))
    # Directory the skill's files are written to under ./skills. Every lineage has
    # its own stable directory so Platform, Organization, and Agent Skills cannot
    # collide when mounted together.
    root_dir: str = SqlField(nullable=False, max_length=255)
    # Every published version must contain this root entrypoint.
    entry_path: str = SqlField(nullable=False, max_length=512, default=DEFAULT_ENTRY_PATH)
    source: SkillSource = SqlField(sa_column=Column(sa.String(), nullable=False))
    # Denormalized latest-version metadata used by list/assignment reads. The
    # immutable copy is stored on SkillVersion as well.
    required_providers: list[SecretProvider] = SqlField(
        default_factory=list,
        sa_column=Column(sa.JSON(), nullable=False, server_default="[]"),
    )
    # Only an override: when NULL the pointer is derived from name + description +
    # entry path. The built-ins carry curated wording here.
    tools_pointer: str | None = SqlField(default=None, sa_column=Column(sa.Text(), nullable=True))


@dataclass(frozen=True)
class PinnedSkill:
    """A loaded skill lineage paired with the exact version an agent mounts."""

    skill: Skill
    version: int


class SkillVersion(BaseModel, table=True):
    """An immutable, published content snapshot of a skill lineage."""

    __tablename__: str = "skill_version"

    __table_args__ = (
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_version_skill_version"),
        sa.Index("ix_skill_version_skill_id", "skill_id"),
        sa.Index("ix_skill_version_source_skill", "source_skill_id", "source_skill_version"),
        sa.CheckConstraint(
            "(source_skill_id IS NULL) = (source_skill_version IS NULL)",
            name="ck_skill_version_source_pair",
        ),
        sa.ForeignKeyConstraint(
            ["source_skill_id", "source_skill_version"],
            ["skill_version.skill_id", "skill_version.version"],
            ondelete="RESTRICT",
            name="fk_skill_version_source_version",
        ),
    )

    skill_id: UUID = SqlField(foreign_key="skill.id", nullable=False, ondelete="CASCADE")
    version: int = SqlField(nullable=False)
    description: str | None = SqlField(default=None, nullable=True, max_length=2000)
    required_providers: list[SecretProvider] = SqlField(
        default_factory=list,
        sa_column=Column(sa.JSON(), nullable=False, server_default="[]"),
    )
    # Set only when this version is a copied snapshot of another Skill Version.
    # A NULL source identifies a Platform Skill or a standalone new lineage.
    source_skill_id: UUID | None = SqlField(default=None, nullable=True)
    source_skill_version: int | None = SqlField(default=None, nullable=True)
    created_by: UUID | None = SqlField(default=None, foreign_key="user.id", nullable=True, ondelete="SET NULL")


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


class SkillDraft(BaseModel, table=True):
    """An unpublished, in-progress set of file edits for a skill lineage.

    At most one per lineage (enforced by the unique constraint), mutated in place
    while editing. Publishing turns its files into the next immutable skill_version
    and deletes this row. Name remains lineage metadata and is edited directly;
    description and required providers are staged here and applied on publish.
    """

    __tablename__: str = "skill_draft"

    __table_args__ = (
        sa.UniqueConstraint("skill_id", name="uq_skill_draft_skill_id"),
        sa.CheckConstraint(
            "(source_skill_id IS NULL) = (source_skill_version IS NULL)",
            name="ck_skill_draft_source_pair",
        ),
        sa.ForeignKeyConstraint(
            ["source_skill_id", "source_skill_version"],
            ["skill_version.skill_id", "skill_version.version"],
            ondelete="RESTRICT",
            name="fk_skill_draft_source_version",
        ),
    )

    skill_id: UUID = SqlField(foreign_key="skill.id", nullable=False, ondelete="CASCADE")
    # Draft metadata: staged here and only applied to the skill row on publish,
    # so the published version's metadata stays frozen until a draft is published.
    description: str | None = SqlField(default=None, nullable=True, max_length=2000)
    required_providers: list[str] = SqlField(
        default_factory=list,
        sa_column=Column(sa.JSON(), nullable=False, server_default="[]"),
    )
    # A fork draft remembers the exact source snapshot it was copied from. The
    # reference advances only when Apply Update replaces the draft.
    source_skill_id: UUID | None = SqlField(default=None, nullable=True)
    source_skill_version: int | None = SqlField(default=None, nullable=True)


class SkillDraftFile(BaseModel, table=True):
    __tablename__: str = "skill_draft_file"

    __table_args__ = (
        sa.UniqueConstraint("skill_draft_id", "path", name="uq_skill_draft_file_draft_path"),
        sa.Index("ix_skill_draft_file_draft_id", "skill_draft_id"),
    )

    skill_draft_id: UUID = SqlField(foreign_key="skill_draft.id", nullable=False, ondelete="CASCADE")
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
    """Name-only edit. Content metadata changes go through draft/publish."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)


class SkillRead(PydanticBaseModel):
    """Lineage-level view of a Skill and its current source/update state."""

    id: UUID
    organization_id: UUID | None
    agent_id: UUID | None
    scope: SkillScope
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

    @model_validator(mode="before")
    @classmethod
    def derive_scope(cls, value: object) -> object:
        if isinstance(value, dict):
            if "scope" not in value:
                value = {
                    **value,
                    "scope": (
                        SkillScope.AGENT.value
                        if value.get("agent_id") is not None
                        else SkillScope.ORGANIZATION.value
                        if value.get("organization_id") is not None
                        else SkillScope.PLATFORM.value
                    ),
                }
            return value
        attrs = vars(value)
        agent_id = attrs.get("agent_id")
        organization_id = attrs.get("organization_id")
        return {
            "id": attrs["id"],
            "organization_id": organization_id,
            "agent_id": agent_id,
            "scope": (
                SkillScope.AGENT
                if agent_id is not None
                else SkillScope.ORGANIZATION
                if organization_id is not None
                else SkillScope.PLATFORM
            ),
            "name": attrs["name"],
            "slug": attrs["slug"],
            "description": attrs["description"],
            "root_dir": attrs["root_dir"],
            "entry_path": attrs["entry_path"],
            "source": attrs["source"],
            "required_providers": attrs["required_providers"],
            "tools_pointer": attrs["tools_pointer"],
            "created_at": attrs["created_at"],
            "updated_at": attrs["updated_at"],
        }


class SkillSummaryRead(SkillRead):
    """A skill as the Skills UI sees it: lineage plus its latest published version."""

    version: int | None
    has_draft: bool
    source_skill_id: UUID | None = None
    source_skill_version: int | None = None
    update_available: bool = False


class SkillDetailRead(SkillSummaryRead):
    files: list[SkillFileRead]
    # Whether a non-soft-deleted agent in the caller's scope has this skill
    # assigned. The UI uses it to gate whole-lineage deletion.
    is_assigned_to_agent: bool


class SkillVersionRead(PydanticBaseModel):
    """One immutable entry in a Skill lineage's version history."""

    version: int
    description: str | None
    required_providers: list[SecretProvider]
    source_skill_id: UUID | None = None
    source_skill_version: int | None = None
    created_by: UUID | None
    created_at: datetime
    # Whether a non-soft-deleted agent in the caller's organization pins this exact
    # version. The UI uses it to disable the per-version Delete button; the backend
    # enforces the same guard independently.
    is_pinned_by_agent: bool

    model_config = ConfigDict(from_attributes=True)


class SkillVersionDetailRead(SkillVersionRead):
    files: list[SkillFileRead]


class SkillDraftRead(PydanticBaseModel):
    skill_id: UUID
    files: list[SkillFileRead]
    description: str | None
    required_providers: list[SecretProvider]
    source_skill_id: UUID | None = None
    source_skill_version: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SkillDraftUpdate(PydanticBaseModel):
    """Replace draft files and optionally stage metadata.

    An omitted metadata field remains unchanged; an explicit ``null`` clears it.
    """

    files: list[SkillFileInput] = Field(min_length=1)
    description: str | None = Field(default=None, max_length=2000)
    required_providers: list[SecretProvider] | None = None


class SkillFilter(PydanticBaseModel):
    search: str | None = None
    source: SkillSource | None = None


def get_skill_filter(
    search: str | None = Query(default=None),
    source: SkillSource | None = Query(default=None),
) -> SkillFilter:
    return SkillFilter(search=search, source=source)
