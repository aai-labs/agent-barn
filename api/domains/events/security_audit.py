from collections.abc import Sequence
from dataclasses import dataclass

from api.domains.events.catalog import (
    AGENT_ACCESS_GRANTED,
    AGENT_ACCESS_REVOKED,
    AGENT_GENERAL_ACCESS_CHANGED,
    ORGANIZATION_ROLE_CHANGED,
    SECURITY_AUDIT_HANDLER,
)
from api.domains.events.handlers import EventDeliveryContext, SupportedEvent
from api.domains.events.models import DomainEventEnvelope


@dataclass
class SecurityAuditProjection:
    """Placeholder sink for the RBAC audit Domain Events registered in AF-219.

    Projecting these events into a durable Security Audit Record is explicitly out of
    scope for AF-219 (see docs/features/domain-events.md); this handler exists only so
    those deliveries reach SUCCEEDED instead of permanently dead-lettering with
    UNKNOWN_HANDLER until the real projection is built.
    """

    name = SECURITY_AUDIT_HANDLER
    supported_events: Sequence[SupportedEvent] = (
        SupportedEvent(ORGANIZATION_ROLE_CHANGED, 1),
        SupportedEvent(AGENT_ACCESS_GRANTED, 1),
        SupportedEvent(AGENT_ACCESS_REVOKED, 1),
        SupportedEvent(AGENT_GENERAL_ACCESS_CHANGED, 1),
    )

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        return None
