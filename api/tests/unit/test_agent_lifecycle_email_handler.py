from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from api.domains.agents.event_handlers import AgentLifecycleEmailHandler
from api.domains.agents.repository import AgentLifecycleEmailRecipient
from api.domains.events.catalog import AGENT_STARTED
from api.domains.events.handlers import EventDeliveryContext, RetryableEventHandlerError
from api.domains.events.models import (
    ActorIdentity,
    ActorIdentityType,
    DomainEventEnvelope,
    SubjectIdentity,
    SubjectIdentityType,
)


class FakeRepository:
    def __init__(self, recipients):
        self.recipients = recipients
        self.notified: dict[UUID, set[str]] = {}

    def find_lifecycle_email_recipients(self, agent_id, organization_id):
        return self.recipients

    def find_notified_lifecycle_email_recipients(self, delivery_id):
        return set(self.notified.get(delivery_id, set()))

    def record_lifecycle_email_recipient_notified(self, delivery_id, recipient_email):
        self.notified.setdefault(delivery_id, set()).add(recipient_email)


class FakeEmailService:
    def __init__(self, result=True, failing_emails: set[str] | None = None):
        self.result = result
        self.failing_emails = failing_emails or set()
        self.sent = []

    def send_agent_lifecycle_email(self, **kwargs):
        self.sent.append(kwargs)
        if kwargs["receiver_email"] in self.failing_emails:
            return False
        return self.result


def _event():
    organization_id = uuid4()
    agent_id = uuid4()
    return DomainEventEnvelope(
        event_name=AGENT_STARTED,
        schema_version=1,
        organization_id=organization_id,
        occurred_at=datetime.now(UTC),
        actor=ActorIdentity(type=ActorIdentityType.USER, id=uuid4(), organization_id=organization_id),
        subject=SubjectIdentity(type=SubjectIdentityType.AGENT, id=agent_id, organization_id=organization_id),
        correlation_id=uuid4(),
        payload={
            "organization_id": str(organization_id),
            "agent_id": str(agent_id),
            "agent_name": "Research Bot",
            "previous_status": "STOPPED",
            "new_status": "RUNNING",
            "platform": "slack",
            "runtime": "openclaw",
        },
    )


def _context(event):
    return EventDeliveryContext(
        delivery_id=uuid4(),
        event_id=event.event_id,
        handler_name="agent.lifecycle_email.notification",
        attempt_count=1,
        correlation_id=event.correlation_id,
        organization_id=event.organization_id,
    )


def test_agent_lifecycle_email_handler_sends_to_creator_and_agent_owners():
    event = _event()
    email_service = FakeEmailService()
    handler = AgentLifecycleEmailHandler(
        repository=FakeRepository([AgentLifecycleEmailRecipient("owner@example.com", "Owner")]),
        email_service=email_service,
    )

    handler.handle(event, _context(event))

    assert email_service.sent == [
        {
            "receiver_email": "owner@example.com",
            "receiver_name": "Owner",
            "agent_name": "Research Bot",
            "lifecycle_action": "started",
        }
    ]


def test_agent_lifecycle_email_handler_retries_when_email_fails():
    event = _event()
    handler = AgentLifecycleEmailHandler(
        repository=FakeRepository([AgentLifecycleEmailRecipient("owner@example.com", "Owner")]),
        email_service=FakeEmailService(result=False),
    )

    with pytest.raises(RetryableEventHandlerError):
        handler.handle(event, _context(event))


def test_agent_lifecycle_email_handler_does_not_resend_to_already_notified_recipients_on_retry():
    event = _event()
    context = _context(event)
    repository = FakeRepository(
        [
            AgentLifecycleEmailRecipient("owner@example.com", "Owner"),
            AgentLifecycleEmailRecipient("creator@example.com", "Creator"),
        ]
    )
    email_service = FakeEmailService(failing_emails={"creator@example.com"})
    handler = AgentLifecycleEmailHandler(repository=repository, email_service=email_service)

    with pytest.raises(RetryableEventHandlerError):
        handler.handle(event, context)

    assert {call["receiver_email"] for call in email_service.sent} == {"owner@example.com", "creator@example.com"}

    # Retry with the same delivery: the previously-succeeded recipient must not be re-emailed.
    email_service.sent.clear()
    email_service.failing_emails = set()
    handler.handle(event, context)

    assert [call["receiver_email"] for call in email_service.sent] == ["creator@example.com"]
