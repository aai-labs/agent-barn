import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from injector import inject

from api.domains.events.catalog import (
    ORGANIZATION_LLM_BUDGET_EMAIL_HANDLER,
    ORGANIZATION_LLM_BUDGET_EXHAUSTED,
    ORGANIZATION_LLM_BUDGET_THRESHOLD_REACHED,
)
from api.domains.events.handlers import (
    EventDeliveryContext,
    RetryableEventHandlerError,
    SupportedEvent,
    TerminalEventHandlerError,
)
from api.domains.events.models import DomainEventEnvelope
from api.domains.organizations.repository import OrganizationRepository
from api.infrastructure.email.exceptions import (
    RetryableEmailSendingException,
    TerminalEmailSendingException,
)
from api.infrastructure.email.service import EmailService

logger = logging.getLogger(__name__)


def _format_usd(value: float, limit: float) -> str:
    # Matches the card: a sub-dollar limit must not render as "$0.00".
    digits = 4 if 0 < limit < 1 else 2
    return f"${value:,.{digits}f}"


@inject
@dataclass
class OrganizationBudgetEmailHandler:
    repository: OrganizationRepository
    email_service: EmailService

    name: ClassVar[str] = ORGANIZATION_LLM_BUDGET_EMAIL_HANDLER
    supported_events: ClassVar[Sequence[SupportedEvent]] = (
        SupportedEvent(ORGANIZATION_LLM_BUDGET_THRESHOLD_REACHED, 1),
        SupportedEvent(ORGANIZATION_LLM_BUDGET_EXHAUSTED, 1),
    )

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        if event.organization_id is None:
            raise TerminalEventHandlerError("Budget event requires an Organization")
        organization_id = UUID(str(event.payload["organization_id"]))
        exhausted = event.event_name == ORGANIZATION_LLM_BUDGET_EXHAUSTED
        headline, body = self._message(event.payload, exhausted=exhausted)
        organization_name = str(event.payload["subject_display"])

        recipients = [
            (email, name, f"You received this because you are an owner or admin of {organization_name}.")
            for email, name in self.repository.find_budget_email_recipients(organization_id)
        ]
        if exhausted:
            # Only the cut-off is ours to act on; an Organization merely approaching
            # its limit is its own business.
            # Lowercased: both lookups dedupe that way, so comparing raw would mail
            # someone twice when their two records differ only in case.
            addressed = {email.lower() for email, _, _ in recipients}
            recipients += [
                (
                    email,
                    name,
                    "You received this because you are a platform administrator.",
                )
                for email, name in self.repository.find_platform_admin_recipients()
                if email.lower() not in addressed
            ]

        # A retry re-runs this handler from scratch, so skip anyone already emailed for
        # this delivery rather than notifying them twice.
        already_notified = self.repository.find_notified_budget_recipients(context.delivery_id)
        retryable: list[str] = []
        terminal: list[str] = []
        for email, full_name, reason in recipients:
            if email in already_notified:
                continue
            try:
                self.email_service.send_organization_budget_email(
                    receiver_email=email,
                    receiver_name=full_name,
                    organization_name=organization_name,
                    headline=headline,
                    body=body,
                    reason=reason,
                )
            except RetryableEmailSendingException:
                retryable.append(email)
                continue
            except TerminalEmailSendingException:
                terminal.append(email)
                continue
            except Exception:
                # Unclassified failure: retry rather than drop the notification.
                logger.exception("Unexpected error sending organization budget email")
                retryable.append(email)
                continue
            self.repository.record_budget_recipient_notified(context.delivery_id, email)

        if retryable:
            raise RetryableEventHandlerError(f"{len(retryable)} budget notification(s) failed transiently")
        if terminal:
            raise TerminalEventHandlerError(f"{len(terminal)} budget notification(s) cannot be delivered")

    @staticmethod
    def _message(payload: dict, *, exhausted: bool) -> tuple[str, str]:
        limit = float(payload["limit_usd"])
        used = f"{_format_usd(float(payload['spend_usd']), limit)} of {_format_usd(limit, limit)}"
        renews = payload.get("renews_at")
        # Deliberately says nothing about where the figure comes from — the recipient
        # cares what they can spend, not which system counted it.
        if exhausted:
            headline = "Model spend limit reached"
            body = (
                f"Your organization has used its entire model spend limit ({used}). "
                "Agents can't make model calls until the limit resets or is raised."
            )
        else:
            headline = f"{payload['threshold_percent']}% of your model spend limit used"
            body = f"Your organization has used {used} of its model spend limit."
        if renews:
            body = f"{body} It resets on {str(renews)[:10]}."
        return headline, body
