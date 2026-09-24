import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from injector import inject

from api.domains.agents.repository import AgentRepository
from api.domains.events.catalog import (
    AGENT_LIFECYCLE_EMAIL_HANDLER,
    AGENT_LLM_BUDGET_EMAIL_HANDLER,
    AGENT_LLM_BUDGET_EXHAUSTED,
    AGENT_LLM_BUDGET_THRESHOLD_REACHED,
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
from api.domains.organizations.lookup import OrganizationLookupService
from api.infrastructure.email.exceptions import (
    RetryableEmailSendingException,
    TerminalEmailSendingException,
)
from api.infrastructure.email.service import EmailService

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


def _format_usd(value: float, limit: float) -> str:
    # Same rule as the Organization's email: a sub-dollar limit must not read "$0.00".
    digits = 4 if 0 < limit < 1 else 2
    return f"${value:,.{digits}f}"


@inject
@dataclass
class AgentBudgetEmailHandler:
    """Tells an Agent's creator and Owners when it nears or reaches its own limit.

    The same audience as its lifecycle emails, and deliberately not platform
    administrators: one Agent running out is its Organization's business, and
    telling the platform about every Agent would bury the Organization-wide alert.
    """

    repository: AgentRepository
    email_service: EmailService
    organization_lookup: OrganizationLookupService

    name: ClassVar[str] = AGENT_LLM_BUDGET_EMAIL_HANDLER
    supported_events: ClassVar[Sequence[SupportedEvent]] = (
        SupportedEvent(AGENT_LLM_BUDGET_THRESHOLD_REACHED, 1),
        SupportedEvent(AGENT_LLM_BUDGET_EXHAUSTED, 1),
    )

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        if event.organization_id is None:
            raise TerminalEventHandlerError("Agent budget event requires an Organization")
        agent_id = UUID(str(event.payload["agent_id"]))
        agent_name = str(event.payload["subject_display"])
        organization_name = self.organization_lookup.get_name(event.organization_id)
        headline, body = self._message(
            event.payload,
            agent_name=agent_name,
            organization_name=organization_name,
            exhausted=event.event_name == AGENT_LLM_BUDGET_EXHAUSTED,
        )
        reason = f"You received this because you own {agent_name}."

        # A retry re-runs the handler from scratch; skip anyone already emailed for
        # this delivery rather than notifying them twice.
        already_notified = self.repository.find_notified_lifecycle_email_recipients(context.delivery_id)
        retryable: list[str] = []
        terminal: list[str] = []
        for recipient in self.repository.find_lifecycle_email_recipients(agent_id, event.organization_id):
            if recipient.email in already_notified:
                continue
            try:
                self.email_service.send_organization_budget_email(
                    receiver_email=recipient.email,
                    receiver_name=recipient.full_name,
                    organization_name=agent_name,
                    headline=headline,
                    body=body,
                    reason=reason,
                )
            except RetryableEmailSendingException:
                retryable.append(recipient.email)
                continue
            except TerminalEmailSendingException:
                terminal.append(recipient.email)
                continue
            except Exception:
                logger.exception("Unexpected error sending agent budget email")
                retryable.append(recipient.email)
                continue
            self.repository.record_lifecycle_email_recipient_notified(context.delivery_id, recipient.email)

        if retryable:
            raise RetryableEventHandlerError(f"{len(retryable)} agent budget notification(s) failed transiently")
        if terminal:
            raise TerminalEventHandlerError(f"{len(terminal)} agent budget notification(s) cannot be delivered")

    @staticmethod
    def _message(payload: dict, *, agent_name: str, organization_name: str, exhausted: bool) -> tuple[str, str]:
        limit = float(payload["limit_usd"])
        used = f"{_format_usd(float(payload['spend_usd']), limit)} of {_format_usd(limit, limit)}"
        if exhausted:
            headline = f"{agent_name} reached its model spend limit"
            body = (
                f"{agent_name} in {organization_name} has used its entire model spend limit ({used}). "
                "It can't make model calls until the limit resets or is raised."
            )
        else:
            headline = f"{agent_name} has used {payload['threshold_percent']}% of its model spend limit"
            body = f"{agent_name} in {organization_name} has used {used} of its model spend limit."
        renews = payload.get("renews_at")
        if renews:
            body = f"{body} It resets on {str(renews)[:10]}."
        return headline, body
