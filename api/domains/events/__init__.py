"""Internal Domain Event contract and registry."""

from api.domains.events.models import (
    ActorIdentity,
    ActorIdentityType,
    DomainEventEnvelope,
    EventDelivery,
    EventDeliveryStatus,
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
    "EventDelivery",
    "EventDeliveryStatus",
    "DomainEventValidationError",
    "EventPayload",
    "OutboxMessage",
    "SubjectIdentity",
    "SubjectIdentityType",
    "UnsupportedDomainEventError",
]
