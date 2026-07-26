from dataclasses import dataclass
from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from injector import inject

from api.domains.agents.repository import AgentLifecycleEmailRecipient
from api.domains.events.catalog import AGENT_LIFECYCLE_EMAIL_HANDLER, AGENT_STARTED, AGENT_STOPPED
from api.domains.events.handlers import EventDeliveryContext, RetryableEventHandlerError, SupportedEvent
from api.domains.events.models import DomainEventEnvelope


class AgentLifecycleEmailRepository(Protocol):
    def find_lifecycle_email_recipients(
        self, agent_id: UUID, organization_id: UUID
    ) -> list[AgentLifecycleEmailRecipient]: ...


class AgentLifecycleEmailService(Protocol):
    def send_agent_lifecycle_email(
        self,
        *,
        receiver_email: str,
        receiver_name: str | None,
        agent_name: str,
        lifecycle_action: str,
    ) -> bool: ...


@inject
@dataclass
class AgentLifecycleEmailHandler:
    repository: AgentLifecycleEmailRepository
    email_service: AgentLifecycleEmailService

    name = AGENT_LIFECYCLE_EMAIL_HANDLER
    supported_events: Sequence[SupportedEvent] = (SupportedEvent(AGENT_STARTED, 1), SupportedEvent(AGENT_STOPPED, 1))

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        agent_id = UUID(str(event.payload["agent_id"]))
        agent_name = str(event.payload["agent_name"])
        action = "started" if event.event_name == AGENT_STARTED else "stopped"
        recipients = self.repository.find_lifecycle_email_recipients(agent_id, event.organization_id)
        failed_recipients: list[str] = []
        for recipient in recipients:
            sent = self.email_service.send_agent_lifecycle_email(
                receiver_email=recipient.email,
                receiver_name=recipient.full_name,
                agent_name=agent_name,
                lifecycle_action=action,
            )
            if not sent:
                failed_recipients.append(recipient.email)
        if failed_recipients:
            raise RetryableEventHandlerError(f"Agent lifecycle email failed for {len(failed_recipients)} recipient(s)")
