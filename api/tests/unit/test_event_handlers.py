from collections.abc import Sequence
from dataclasses import dataclass

import pytest

from api.domains.events import DomainEventValidationError
from api.domains.events.handlers import EventDeliveryContext, EventHandlerRegistry, SupportedEvent
from api.domains.events.models import DomainEventEnvelope


@dataclass
class RecordingHandler:
    name: str = "audit.projection"
    supported_events: Sequence[SupportedEvent] = (SupportedEvent("agent.sampled", 1),)

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        pass


def test_handler_registry_requires_unique_stable_names():
    with pytest.raises(DomainEventValidationError, match="already registered"):
        EventHandlerRegistry([RecordingHandler(), RecordingHandler()])


def test_handler_registry_rejects_empty_handler_name():
    with pytest.raises(DomainEventValidationError, match="name is required"):
        EventHandlerRegistry([RecordingHandler(name="")])


def test_handler_registry_rejects_handlers_without_supported_events():
    with pytest.raises(DomainEventValidationError, match="must declare supported events"):
        EventHandlerRegistry([RecordingHandler(supported_events=())])


def test_handler_registry_rejects_duplicate_supported_events_for_one_handler():
    supported = (SupportedEvent("agent.sampled", 1), SupportedEvent("agent.sampled", 1))

    with pytest.raises(DomainEventValidationError, match="duplicate supported events"):
        EventHandlerRegistry([RecordingHandler(supported_events=supported)])


def test_handler_registry_checks_event_version_support():
    registry = EventHandlerRegistry([RecordingHandler()])

    assert registry.supports("audit.projection", "agent.sampled", 1) is True
    assert registry.supports("audit.projection", "agent.sampled", 2) is False
