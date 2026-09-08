import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from injector import inject

from api.core.config import Config
from api.domains.agents.repository import AgentRepository
from api.domains.events.catalog import (
    AGENT_DELETED,
    AGENT_LIFECYCLE_EMAIL_HANDLER,
    AGENT_MEMORY_PURGE_HANDLER,
    AGENT_STARTED,
    AGENT_STOPPED,
)
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
from api.infrastructure.honcho.client import HonchoClient, HonchoError, workspace_id_for_agent

logger = logging.getLogger(__name__)


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
            except Exception:
                # Unclassified failure: retry rather than drop the notification.
                logger.exception("Unexpected error sending agent lifecycle email to %s", recipient.email)
                retryable_recipients.append(recipient.email)
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


@inject
@dataclass
class AgentMemoryPurgeHandler:
    """Erase a deleted Agent's memory.

    Deleting an Agent already destroys its volume, secret, and every other trace,
    and there is no restore path — retaining derived conclusions about real people,
    owned by an Agent nobody owns and under no retention policy, would be the odd
    exception rather than a safeguard. Anything worth keeping is copied out first
    through the carry-over the delete flow offers.

    This runs as a retried delivery rather than inline in `delete_agent` because
    Honcho refuses a workspace delete while any session remains (409), and both the
    session and workspace deletes are accepted asynchronously — so the purge can
    lose that race. Inline, a lost race would leave the memory behind with only a
    log line; here it is retried until it takes.
    """

    honcho: HonchoClient
    config: Config

    name: ClassVar[str] = AGENT_MEMORY_PURGE_HANDLER
    supported_events: ClassVar[Sequence[SupportedEvent]] = (SupportedEvent(AGENT_DELETED, 1),)

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        if not self.config.honcho_enabled:
            # No workspace was ever created, so there is nothing to erase. Not an
            # error: the same deployment may enable memory later.
            return
        agent_id = UUID(str(event.payload["agent_id"]))
        try:
            self.honcho.delete_workspace(workspace_id_for_agent(agent_id))
        except HonchoError as exc:
            # Retryable, deliberately: the common cause is Honcho still clearing
            # sessions. Giving up would leave a deleted Agent's memory in place with
            # nothing left in the product able to reach it.
            raise RetryableEventHandlerError(f"Could not erase memory for agent {agent_id}: {exc}") from exc
