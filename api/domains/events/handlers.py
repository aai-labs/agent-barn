from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from api.domains.events.models import DomainEventEnvelope
from api.domains.events.registry import DomainEventValidationError


class EventHandlerError(Exception):
    """Base class for Event Handler failures."""


class RetryableEventHandlerError(EventHandlerError):
    """Failure that should follow the Dramatiq retry path."""


class TerminalEventHandlerError(EventHandlerError):
    """Failure that should dead-letter the Event Delivery without retrying."""


@dataclass(frozen=True)
class EventDeliveryContext:
    delivery_id: UUID
    event_id: UUID
    handler_name: str
    attempt_count: int
    correlation_id: UUID
    organization_id: UUID


@dataclass(frozen=True)
class SupportedEvent:
    event_name: str
    schema_version: int

    def __post_init__(self) -> None:
        if not self.event_name:
            raise DomainEventValidationError("Event Handler supported event name is required")
        if self.schema_version < 1:
            raise DomainEventValidationError("Event Handler supported schema version must be at least 1")


class EventHandler(Protocol):
    # Read-only properties, not plain attributes: implementations declare these as
    # ClassVar constants, and the registry only ever reads them.
    @property
    def name(self) -> str: ...

    @property
    def supported_events(self) -> Sequence[SupportedEvent]: ...

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None: ...


class UnknownEventHandlerError(DomainEventValidationError):
    pass


class UnsupportedHandlerEventError(DomainEventValidationError):
    pass


class EventHandlerRegistry:
    def __init__(self, handlers: Iterable[EventHandler] = ()):
        self._handlers: dict[str, EventHandler] = {}
        for handler in handlers:
            self.register(handler)

    def register(self, handler: EventHandler) -> None:
        if not handler.name:
            raise DomainEventValidationError("Event Handler name is required")
        if handler.name in self._handlers:
            raise DomainEventValidationError(f"Event Handler {handler.name} is already registered")
        supported_events = tuple(handler.supported_events)
        if not supported_events:
            raise DomainEventValidationError(f"Event Handler {handler.name} must declare supported events")
        if len(set(supported_events)) != len(supported_events):
            raise DomainEventValidationError(f"Event Handler {handler.name} declares duplicate supported events")
        self._handlers[handler.name] = handler

    def get(self, handler_name: str) -> EventHandler:
        handler = self._handlers.get(handler_name)
        if handler is None:
            raise UnknownEventHandlerError(f"Unknown Event Handler {handler_name}")
        return handler

    def supports(self, handler_name: str, event_name: str, schema_version: int) -> bool:
        handler = self.get(handler_name)
        return SupportedEvent(event_name, schema_version) in set(handler.supported_events)

    def require_support(self, handler_name: str, event_name: str, schema_version: int) -> None:
        if not self.supports(handler_name, event_name, schema_version):
            raise UnsupportedHandlerEventError(
                f"Event Handler {handler_name} does not support {event_name} v{schema_version}"
            )
