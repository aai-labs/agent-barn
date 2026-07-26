from datetime import UTC, datetime
from uuid import uuid4

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

    def find_lifecycle_email_recipients(self, agent_id, organization_id):
        return self.recipients


class FakeEmailService:
    def __init__(self, result=True):
        self.result = result
        self.sent = []

    def send_agent_lifecycle_email(self, **kwargs):
        self.sent.append(kwargs)
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
