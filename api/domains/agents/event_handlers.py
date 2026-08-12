from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from injector import inject

from api.domains.agents.repository import AgentRepository
from api.domains.events.catalog import AGENT_LIFECYCLE_EMAIL_HANDLER, AGENT_STARTED, AGENT_STOPPED
from api.domains.events.handlers import (
    EventDeliveryContext,
    RetryableEventHandlerError,
    SupportedEvent,
    TerminalEventHandlerError,
)
from api.domains.events.models import DomainEventEnvelope
from api.infrastructure.email.exceptions import (
    RetryableEmailSendingException,
    TerminalEmailSendingException,
)
from api.infrastructure.email.service import EmailService


@inject
@dataclass
class AgentLifecycleEmailHandler:
    repository: AgentRepository
    email_service: EmailService

    name: ClassVar[str] = AGENT_LIFECYCLE_EMAIL_HANDLER
    supported_events: ClassVar[Sequence[SupportedEvent]] = (
        SupportedEvent(AGENT_STARTED, 1),
        SupportedEvent(AGENT_STOPPED, 1),
    )

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        agent_id = UUID(str(event.payload["agent_id"]))
        if event.organization_id is None:
            raise TerminalEventHandlerError("Agent lifecycle event requires an Organization")
        agent_name = str(event.payload["agent_name"])
        action = "started" if event.event_name == AGENT_STARTED else "stopped"
        recipients = self.repository.find_lifecycle_email_recipients(agent_id, event.organization_id)
        # A retry re-runs this handler from scratch; skip recipients already notified for
        # this delivery so a retry (after some recipients failed) doesn't resend to the
        # ones that already succeeded.
        already_notified = self.repository.find_notified_lifecycle_email_recipients(context.delivery_id)
        pending_recipients = [recipient for recipient in recipients if recipient.email not in already_notified]
        retryable_recipients: list[str] = []
        terminal_recipients: list[str] = []
        for recipient in pending_recipients:
            try:
                self.email_service.send_agent_lifecycle_email(
                    receiver_email=recipient.email,
                    receiver_name=recipient.full_name,
                    agent_name=agent_name,
                    lifecycle_action=action,
                )
            except RetryableEmailSendingException:
                retryable_recipients.append(recipient.email)
                continue
            except TerminalEmailSendingException:
                terminal_recipients.append(recipient.email)
                continue
            self.repository.record_lifecycle_email_recipient_notified(context.delivery_id, recipient.email)
        # A retryable failure anywhere wins: rescheduling gives the terminal recipients no
        # extra sends (they're re-classified next attempt) but rescues the transient ones.
        if retryable_recipients:
            raise RetryableEventHandlerError(
                f"Agent lifecycle email failed for {len(retryable_recipients)} recipient(s)"
            )
        if terminal_recipients:
            raise TerminalEventHandlerError(
                f"Agent lifecycle email permanently failed for {len(terminal_recipients)} recipient(s)"
            )
