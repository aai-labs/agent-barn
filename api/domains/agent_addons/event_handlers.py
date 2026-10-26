import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from injector import inject

from api.core.config import Config
from api.domains.agent_addons.models import addon_summary
from api.domains.agent_addons.repository import AgentAddonRepository
from api.domains.events.catalog import (
    AGENT_ADDON_APPROVED,
    AGENT_ADDON_EMAIL_HANDLER,
    AGENT_ADDON_REJECTED,
    AGENT_ADDON_REQUESTED,
    AGENT_ADDON_REVOKED,
)
from api.domains.events.handlers import (
    EventDeliveryContext,
    RetryableEventHandlerError,
    SupportedEvent,
    TerminalEventHandlerError,
)
from api.domains.events.models import DomainEventEnvelope
from api.domains.organizations.repository import OrganizationRepository
from api.infrastructure.email.exceptions import RetryableEmailSendingException, TerminalEmailSendingException
from api.infrastructure.email.service import EmailService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Message:
    headline: str
    body: str
    detail_label: str
    detail: str
    action_label: str
    action_path: str


@inject
@dataclass
class AgentAddonEmailHandler:
    """Tells people about an Agent Add-on request that needs them.

    A new request goes to every Platform Administrator, who reviews it; a decision goes to
    whoever asked. A withdrawal emails nobody. Idempotent per recipient, as the budget emails
    are: a retry skips anyone this delivery already reached.
    """

    repository: AgentAddonRepository
    organizations: OrganizationRepository
    email_service: EmailService
    config: Config

    name: ClassVar[str] = AGENT_ADDON_EMAIL_HANDLER
    supported_events: ClassVar[Sequence[SupportedEvent]] = (
        SupportedEvent(AGENT_ADDON_REQUESTED, 1),
        SupportedEvent(AGENT_ADDON_APPROVED, 1),
        SupportedEvent(AGENT_ADDON_REJECTED, 1),
        SupportedEvent(AGENT_ADDON_REVOKED, 1),
    )

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        if event.organization_id is None:
            raise TerminalEventHandlerError("Add-on event requires an Organization")
        payload = event.payload
        organization = self.organizations.get(UUID(str(payload["organization_id"])))
        organization_name = organization.name if organization is not None else "your organization"
        agent_name = str(payload["subject_display"])
        message = self._message(event.event_name, payload, organization_name, agent_name)

        if event.event_name == AGENT_ADDON_REQUESTED:
            recipients = [
                (email, name, "You received this because you are a platform administrator.")
                for email, name in self.organizations.find_platform_admin_recipients()
            ]
        else:
            requester = self.repository.get_requester(UUID(str(payload["addon_id"])))
            # A requester who has since been deleted has no one to tell.
            recipients = (
                [(requester[0], requester[1], "You received this because you requested this add-on.")]
                if requester is not None
                else []
            )

        already_notified = self.repository.find_notified_recipients(context.delivery_id)
        retryable: list[str] = []
        terminal: list[str] = []
        for email, full_name, reason in recipients:
            if email in already_notified:
                continue
            try:
                self.email_service.send_agent_addon_email(
                    receiver_email=email,
                    receiver_name=full_name,
                    organization_name=organization_name,
                    agent_name=agent_name,
                    headline=message.headline,
                    body=message.body,
                    detail_label=message.detail_label,
                    detail=message.detail,
                    action_label=message.action_label,
                    action_url=f"{self.config.web_app_url.rstrip('/')}{message.action_path}",
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
                logger.exception("Unexpected error sending agent add-on email")
                retryable.append(email)
                continue
            self.repository.record_recipient_notified(context.delivery_id, email)

        if retryable:
            raise RetryableEventHandlerError(f"{len(retryable)} add-on notification(s) failed transiently")
        if terminal:
            raise TerminalEventHandlerError(f"{len(terminal)} add-on notification(s) cannot be delivered")

    @staticmethod
    def _message(event_name: str, payload: dict, organization_name: str, agent_name: str) -> _Message:
        summary = addon_summary(str(payload["kind"]), str(payload["name"]), payload)
        configuration = (
            f"/dashboard/{payload['organization_id']}/agents/{payload['agent_id']}/configuration?section=addons"
        )
        if event_name == AGENT_ADDON_REQUESTED:
            return _Message(
                headline=f"Add-on waiting for review: {payload['name']}",
                body=(
                    f"{payload['actor_display']} at {organization_name} asked to install the {summary} "
                    f"on the agent {agent_name}."
                ),
                detail_label="Why:",
                detail=str(payload["request_reason"]),
                action_label="Review add-on requests",
                action_path="/dashboard/platform/agent-addons?state=PENDING",
            )
        if event_name == AGENT_ADDON_APPROVED:
            return _Message(
                headline=f"Add-on approved: {payload['name']}",
                body=(
                    f"The {summary} was approved for {agent_name}. "
                    "It is installed the next time the agent starts, so restart the agent to use it now."
                ),
                detail_label="You asked for it because:",
                detail=str(payload["request_reason"]),
                action_label="Open the agent's add-ons",
                action_path=configuration,
            )
        if event_name == AGENT_ADDON_REJECTED:
            return _Message(
                headline=f"Add-on not approved: {payload['name']}",
                body=f"The {summary} was not approved for {agent_name}.",
                detail_label="Reason:",
                detail=str(payload["reason"]),
                action_label="Open the agent's add-ons",
                action_path=configuration,
            )
        return _Message(
            headline=f"Add-on approval withdrawn: {payload['name']}",
            body=(
                f"The approval of the {summary} for {agent_name} was withdrawn by a platform administrator. "
                "The agent no longer has it after its next start."
            ),
            detail_label="You asked for it because:",
            detail=str(payload["request_reason"]),
            action_label="Open the agent's add-ons",
            action_path=configuration,
        )
