from datetime import UTC, datetime
from uuid import uuid4

import pytest
from hamcrest import assert_that, empty, equal_to, has_length

from api.domains.agents.event_handlers import AgentLifecycleEmailHandler
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.events.catalog import AGENT_LIFECYCLE_EMAIL_HANDLER, AGENT_STARTED
from api.domains.events.handlers import EventDeliveryContext, RetryableEventHandlerError
from api.domains.events.models import (
    ActorIdentity,
    ActorIdentityType,
    DomainEventEnvelope,
    EventScope,
    SubjectIdentity,
    SubjectIdentityType,
)
from api.infrastructure.email.client import EmailClient
from api.infrastructure.email.models import Email
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector
from api.tests.steps.agent import MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

# End-to-end coverage for the real DI wiring (AppModule -> AgentLifecycleEmailHandler ->
# AgentRepository/EmailService), not just the handler's own orchestration logic — a
# fake-based unit test would not have caught a missing/broken injector binding, which is
# exactly the class of bug this handler shipped with (see AF-220 follow-up).
_GIVEN = [
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
]


def _there_is_a_started_agent():
    def step(context):
        there_is_an_agent(created_by_user_id=context.user.id, status=AgentStatus.STOPPED)(context)

    return step


def _start_agent_and_get_delivery_id(context) -> tuple[DomainEventEnvelope, EventDeliveryContext]:
    """Transition context.agent to RUNNING through the real repository, staging a real
    outbox message + Event Delivery row (agent_lifecycle_email_receipt has a hard FK to
    event_delivery, so a synthetic delivery_id won't do)."""
    repository: AgentRepository = context.injector.get(AgentRepository)
    agent = context.agent
    agent.status = AgentStatus.RUNNING
    result = repository.save_with_lifecycle_event(
        agent,
        event_name=AGENT_STARTED,
        actor=ActorIdentity(type=ActorIdentityType.USER, id=context.user.id, organization_id=context.organization.id),
        previous_status=AgentStatus.STOPPED.value,
        new_status=AgentStatus.RUNNING.value,
    )
    delivery_id = result.delivery_ids[0]

    event = DomainEventEnvelope(
        event_name=AGENT_STARTED,
        schema_version=1,
        event_scope=EventScope.ORGANIZATION,
        organization_id=context.organization.id,
        occurred_at=datetime.now(UTC),
        actor=ActorIdentity(type=ActorIdentityType.USER, id=context.user.id, organization_id=context.organization.id),
        subject=SubjectIdentity(type=SubjectIdentityType.AGENT, id=agent.id, organization_id=context.organization.id),
        correlation_id=uuid4(),
        payload={
            "organization_id": str(context.organization.id),
            "agent_id": str(agent.id),
            "agent_name": agent.name,
            "previous_status": AgentStatus.STOPPED.value,
            "new_status": AgentStatus.RUNNING.value,
            "runtime": agent.agent_type,
        },
    )
    delivery_context = EventDeliveryContext(
        delivery_id=delivery_id,
        event_id=event.event_id,
        handler_name=AGENT_LIFECYCLE_EMAIL_HANDLER,
        attempt_count=1,
        correlation_id=event.correlation_id,
        organization_id=event.organization_id,
    )
    return event, delivery_context


def test_agent_lifecycle_email_handler_sends_to_creator(monkeypatch):
    sent: list[Email] = []

    def fake_send(self, email: Email) -> Email:
        sent.append(email)
        return email

    monkeypatch.setattr(EmailClient, "send", fake_send)

    with given([*_GIVEN, _there_is_a_started_agent()]) as context:
        handler = context.injector.get(AgentLifecycleEmailHandler)
        event, delivery_context = _start_agent_and_get_delivery_id(context)

        handler.handle(event, delivery_context)

        assert_that(sent, has_length(1))
        assert_that(sent[0].to_email, equal_to(context.user.email))

        repository = context.injector.get(AgentRepository)
        notified = repository.find_notified_lifecycle_email_recipients(delivery_context.delivery_id)
        assert_that(notified, equal_to({context.user.email}))


def test_agent_lifecycle_email_handler_raises_retryable_error_when_send_fails(monkeypatch):
    def failing_send(self, email: Email) -> Email:
        raise RuntimeError("simulated SMTP failure")

    monkeypatch.setattr(EmailClient, "send", failing_send)

    with given([*_GIVEN, _there_is_a_started_agent()]) as context:
        handler = context.injector.get(AgentLifecycleEmailHandler)
        event, delivery_context = _start_agent_and_get_delivery_id(context)

        with pytest.raises(RetryableEventHandlerError):
            handler.handle(event, delivery_context)

        repository = context.injector.get(AgentRepository)
        notified = repository.find_notified_lifecycle_email_recipients(delivery_context.delivery_id)
        assert_that(notified, empty())


def test_agent_lifecycle_email_handler_does_not_resend_to_already_notified_recipient_on_retry(monkeypatch):
    sent: list[Email] = []

    def fake_send(self, email: Email) -> Email:
        sent.append(email)
        return email

    monkeypatch.setattr(EmailClient, "send", fake_send)

    with given([*_GIVEN, _there_is_a_started_agent()]) as context:
        handler = context.injector.get(AgentLifecycleEmailHandler)
        event, delivery_context = _start_agent_and_get_delivery_id(context)

        handler.handle(event, delivery_context)
        assert_that(sent, has_length(1))

        # Same delivery retried (e.g. after a different recipient failed): the
        # already-notified recipient must not be re-emailed.
        sent.clear()
        handler.handle(event, delivery_context)
        assert_that(sent, empty())


def test_agent_lifecycle_email_handler_wiring_uses_real_agent_repository_and_email_service():
    """Regression test for the missing-binding bug: build the handler straight from the
    real AppModule injector (no test doubles) and confirm both dependencies resolve to
    the concrete production classes rather than raising or falling back silently."""
    with given([*_GIVEN, _there_is_a_started_agent()]) as context:
        handler = context.injector.get(AgentLifecycleEmailHandler)

        assert_that(type(handler.repository).__name__, equal_to("AgentRepository"))
        assert_that(type(handler.email_service).__name__, equal_to("EmailService"))
