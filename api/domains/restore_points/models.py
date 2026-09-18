from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field

from api.domains.agents.models import (
    AgentTemplateSelection,
    CommandApprovalMode,
    RestorePointOrigin,
    RestorePointStatus,
    SkillVersionPin,
)
from api.infrastructure.shared.models import PaginatedItems

CONFIG_MANIFEST_VERSION = 2

TERMINAL_STATUSES = (RestorePointStatus.READY, RestorePointStatus.FAILED)
NON_TERMINAL_STATUSES = (
    RestorePointStatus.PENDING,
    RestorePointStatus.CAPTURING,
    RestorePointStatus.RESTORING,
    RestorePointStatus.DELETING,
)
ACTIVE_CAPTURE_STATUSES = (RestorePointStatus.PENDING, RestorePointStatus.CAPTURING)


class RestorePointSkill(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    skill_id: UUID
    name: str
    pinned_version: int


class RestorePointConfigManifest(PydanticBaseModel):
    """Display-only record of an Agent's pins at capture time.

    Never holds credentials: the archive lives on a PVC and Agent Secrets stay in
    their own encrypted columns.
    """

    model_config = ConfigDict(extra="forbid")

    version: int = CONFIG_MANIFEST_VERSION
    agent_type: str
    template_key: str = ""
    template_version: int = 0
    # How the pin was made, in the vocabulary select_agent_template accepts, so a
    # replay can hand it straight back rather than guessing which of the two
    # shared sources — platform or organization — this version came from.
    template_selection_type: str = ""
    override_version: int | None = None
    model: str = ""
    effective_model: str = ""
    approval_mode: str = ""
    verbose_mode: bool = False
    skills: list[RestorePointSkill] = Field(default_factory=list)


class AgentRestorePointCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, max_length=120)


class AgentRestorePointRestore(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    # Checked before the Job starts, and applied by the client once the volume is
    # back. Refusing up front is the point: a configuration that cannot be applied
    # must not cost the Agent its files first.
    reapply_configuration: bool = False


def selection_from_manifest(
    manifest: dict[str, Any],
    expected_agent_updated_at: datetime,
) -> AgentTemplateSelection | None:
    """The recorded configuration as a selection, or None if it cannot be replayed.

    Built here rather than by the client so the check that runs before a restore and
    the write that runs after it are reading the same record the same way.
    """
    parsed = RestorePointConfigManifest.model_validate(manifest)
    if parsed.version < CONFIG_MANIFEST_VERSION or not parsed.template_selection_type:
        return None

    skill_ids = [skill.skill_id for skill in parsed.skills]
    skill_versions = [SkillVersionPin(skill_id=skill.skill_id, version=skill.pinned_version) for skill in parsed.skills]
    approval_mode = CommandApprovalMode(parsed.approval_mode) if parsed.approval_mode else None

    if parsed.template_selection_type == "override":
        return AgentTemplateSelection(
            selection_type="override",
            override_version=parsed.override_version or parsed.template_version,
            expected_agent_updated_at=expected_agent_updated_at,
            skill_ids=skill_ids,
            skill_versions=skill_versions,
            model=parsed.model or None,
            approval_mode=approval_mode,
            verbose_mode=parsed.verbose_mode,
        )
    if parsed.template_selection_type not in ("platform", "organization"):
        return None
    return AgentTemplateSelection(
        selection_type=parsed.template_selection_type,
        template_key=parsed.template_key,
        template_version=parsed.template_version,
        expected_agent_updated_at=expected_agent_updated_at,
        skill_ids=skill_ids,
        skill_versions=skill_versions,
        model=parsed.model or None,
        approval_mode=approval_mode,
        verbose_mode=parsed.verbose_mode,
    )


class AgentRestorePointRead(PydanticBaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    label: str | None
    status: RestorePointStatus
    origin: RestorePointOrigin
    agent_type: str
    archive_bytes: int | None
    file_count: int | None
    failure_reason: str | None
    # True while a confirmed restore still owes the Agent its recorded configuration.
    reapply_configuration: bool = False
    # Set when the volume came back but the configuration did not.
    configuration_error: str | None = None
    config_manifest: dict[str, Any]
    created_at: datetime
    captured_at: datetime | None


@dataclass
class AgentRestorePointList(PaginatedItems[AgentRestorePointRead]):
    """The page, plus what the caller needs to decide whether capture is offered.

    ``total`` counts every row an Agent has, including PRE_RESTORE backups and
    failed captures. The cap counts neither, so a client cannot derive its
    remaining headroom from the page alone.
    """

    cap: int
    manual_count: int
