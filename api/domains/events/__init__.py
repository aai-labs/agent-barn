"""Internal Domain Event contract and registry."""

from api.domains.events.dispatch import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.events.handlers import (
    EventDeliveryContext,
    EventHandler,
    EventHandlerError,
    EventHandlerRegistry,
    RetryableEventHandlerError,
    SupportedEvent,
    TerminalEventHandlerError,
)
from api.domains.events.models import (
    ActorIdentity,
    ActorIdentityType,
    DomainEventEnvelope,
    EventDelivery,
    EventDeliveryDeadLetterReason,
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
    "DomainEventValidationError",
    "EventDelivery",
    "EventDeliveryContext",
    "EventDeliveryDeadLetterReason",
    "EventDeliveryDispatcher",
    "EventDeliveryStatus",
    "EventHandler",
    "EventHandlerError",
    "EventHandlerRegistry",
    "EventPayload",
    "OutboxMessage",
    "RetryableEventHandlerError",
    "SubjectIdentity",
    "SubjectIdentityType",
    "SupportedEvent",
    "TerminalEventHandlerError",
    "UnsupportedDomainEventError",
    "resolve_actor_identity",
]
