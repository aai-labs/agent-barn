from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel as PydanticBaseModel
from pydantic import ConfigDict, Field

from api.domains.agents.models import RestorePointOrigin, RestorePointStatus

CONFIG_MANIFEST_VERSION = 1

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
    model: str = ""
    effective_model: str = ""
    approval_mode: str = ""
    verbose_mode: bool = False
    skills: list[RestorePointSkill] = Field(default_factory=list)


class AgentRestorePointCreate(PydanticBaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, max_length=120)


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
    config_manifest: dict[str, Any]
    created_at: datetime
    captured_at: datetime | None
