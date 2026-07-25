"""Internal Domain Event contract and registry."""

from api.domains.events.models import (
    ActorIdentity,
    ActorIdentityType,
    DomainEventEnvelope,
    EventPayload,
    OutboxMessage,
    SubjectIdentity,
    SubjectIdentityType,
)
from api.domains.events.registry import (
    DomainEventDefinition,
    DomainEventRegistry,
    DomainEventValidationError,
    UnsupportedDomainEventError,
)

__all__ = [
    "ActorIdentity",
    "ActorIdentityType",
    "DomainEventDefinition",
    "DomainEventEnvelope",
    "DomainEventRegistry",
    "DomainEventValidationError",
    "EventPayload",
    "OutboxMessage",
    "SubjectIdentity",
    "SubjectIdentityType",
    "UnsupportedDomainEventError",
]
