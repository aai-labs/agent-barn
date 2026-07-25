import enum
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ActorIdentityType(str, enum.Enum):
    MEMBERSHIP = "MEMBERSHIP"
    USER = "USER"
    SYSTEM = "SYSTEM"
    RUNTIME = "RUNTIME"


class SubjectIdentityType(str, enum.Enum):
    AGENT = "AGENT"
    MEMBERSHIP = "MEMBERSHIP"
    ORGANIZATION = "ORGANIZATION"
    TEMPLATE = "TEMPLATE"
    SKILL = "SKILL"
    SYSTEM = "SYSTEM"


class ActorIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: ActorIdentityType
    id: UUID | str
    organization_id: UUID | None = None


class SubjectIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: SubjectIdentityType
    id: UUID | str
    organization_id: UUID | None = None


EventPayload = dict[str, Any]


class DomainEventEnvelope(BaseModel):
    """Typed, tenant-aware internal Domain Event envelope."""

    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    event_name: str = Field(min_length=1, max_length=255)
    schema_version: int = Field(ge=1)
    occurred_at: datetime
    organization_id: UUID
    actor: ActorIdentity
    subject: SubjectIdentity
    correlation_id: UUID
    causation_id: UUID | None = None
    payload: EventPayload
