import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import ClassVar
from uuid import UUID

from injector import inject

from api.core.config import Config
from api.domains.agents.service import AgentService
from api.domains.anomalies.alerts import AlertDecision, alert_decision, describe
from api.domains.anomalies.repository import AnomalyRepository, AnomalySettingsRepository
from api.domains.events.catalog import AGENT_ANOMALY_ALERT_EMAIL_HANDLER, AGENT_ANOMALY_FLAGGED
from api.domains.events.handlers import (
    EventDeliveryContext,
    RetryableEventHandlerError,
    SupportedEvent,
    TerminalEventHandlerError,
)
from api.domains.events.models import DomainEventEnvelope
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.email.exceptions import (
    RetryableEmailSendingException,
    TerminalEmailSendingException,
)
from api.infrastructure.email.service import EmailService

logger = logging.getLogger(__name__)


@inject
@dataclass
class AnomalyAlertEmailHandler:
    """Emails an Organization's Owners and Admins what a check newly flagged for one of
    its Agents, when any of it is worth a look (`alerts.alert_decision`).

    The audience is whoever `anomaly.read` reaches, the same people who can open the
    Unusual activity tab; an Agent's own Owner who is a Member is not among them.

    The Event is recorded before the check classifies what it flagged, so this reads the
    Anomalies as they are now. While one may still be being classified, the delivery is
    retried rather than sent without its classification.

    Whether the Organization still wants alerts is read here too, so turning detection or
    alerts off also stops one already queued.
    """

    repository: AnomalyRepository
    settings_repository: AnomalySettingsRepository
    agent_service: AgentService
    organization_lookup: OrganizationLookupService
    email_service: EmailService
    config: Config

    name: ClassVar[str] = AGENT_ANOMALY_ALERT_EMAIL_HANDLER
    supported_events: ClassVar[Sequence[SupportedEvent]] = (SupportedEvent(AGENT_ANOMALY_FLAGGED, 1),)

    def handle(self, event: DomainEventEnvelope, context: EventDeliveryContext) -> None:
        if event.organization_id is None:
            raise TerminalEventHandlerError("Unusual activity alert requires an Organization")
        organization_id = event.organization_id
        settings = self.settings_repository.get_settings(organization_id)
        if settings is None or not settings.enabled or not settings.alerts_enabled:
            return
        agent_id = UUID(str(event.payload["agent_id"]))
        anomalies = self.repository.get_anomalies([UUID(str(item)) for item in event.payload["anomaly_ids"]])
        now = datetime.now(UTC)
        decisions = [(anomaly, alert_decision(anomaly, now)) for anomaly in anomalies]
        if any(decision is AlertDecision.WAIT for _, decision in decisions):
            raise RetryableEventHandlerError("Flagged activity may still be being classified")
        items = [asdict(describe(anomaly)) for anomaly, decision in decisions if decision is AlertDecision.ALERT]
        if not items:
            return
        agent_name = self.agent_service.agent_name(agent_id)
        if agent_name is None:
            # Deleted since: there is nothing left to look at.
            return

        organization_name = self.organization_lookup.get_name(organization_id)
        reason = f"You received this because you are an owner or admin of {organization_name}."
        link = f"{self.config.web_app_url}/dashboard/{organization_id}/agents/{agent_id}?tab=unusual-activity"

        # A retry re-runs the handler from scratch; skip anyone already emailed for
        # this delivery rather than emailing them twice.
        already_notified = self.repository.find_notified_alert_recipients(context.delivery_id)
        retryable: list[str] = []
        terminal: list[str] = []
        for email, full_name in self.organization_lookup.recipients_with_permission(
            organization_id, PermissionKey.ANOMALY_READ
        ):
            if email in already_notified:
                continue
            try:
                self.email_service.send_anomaly_alert_email(
                    receiver_email=email,
                    receiver_name=full_name,
                    agent_name=agent_name,
                    items=items,
                    link=link,
                    reason=reason,
                )
            except RetryableEmailSendingException:
                retryable.append(email)
                continue
            except TerminalEmailSendingException:
                terminal.append(email)
                continue
            except Exception:
                # Unclassified failure: retry rather than drop the alert.
                logger.exception("Unexpected error sending unusual activity alert")
                retryable.append(email)
                continue
            self.repository.record_alert_recipient_notified(context.delivery_id, email)

        if retryable:
            raise RetryableEventHandlerError(f"{len(retryable)} unusual activity alert(s) failed transiently")
        if terminal:
            raise TerminalEventHandlerError(f"{len(terminal)} unusual activity alert(s) cannot be delivered")
