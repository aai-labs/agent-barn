"""Retry classification in AgentLifecycleEmailHandler.

The handler runs under the delivery framework, so how it *fails* decides whether a delivery
is rescheduled or dead-lettered. A payload Cloudflare will never accept must not burn the
retry budget, and a transient failure must not be discarded. DI wiring is covered
end-to-end in `tests/integration/test_agent_lifecycle_email_handler.py`; this file covers
the branching with fakes.
"""

from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

from hamcrest import assert_that, calling, empty, equal_to, raises

from api.domains.agents.event_handlers import AgentLifecycleEmailHandler
from api.domains.agents.repository import AgentLifecycleEmailRecipient, AgentRepository
from api.domains.events.catalog import AGENT_LIFECYCLE_EMAIL_HANDLER, AGENT_STARTED
from api.domains.events.handlers import (
    EventDeliveryContext,
    RetryableEventHandlerError,
    TerminalEventHandlerError,
)
from api.domains.events.models import (
    ActorIdentity,
    ActorIdentityType,
    DomainEventEnvelope,
    EventScope,
    SubjectIdentity,
    SubjectIdentityType,
)
from api.infrastructure.email.exceptions import (
    RetryableEmailSendingException,
    TerminalEmailSendingException,
)
from api.infrastructure.email.service import EmailService

ORG_ID = uuid4()
AGENT_ID = uuid4()
DELIVERY_ID = uuid4()


class _FakeRepository:
    def __init__(self, recipients: list[str], already_notified: set[str] | None = None):
        self._recipients = [AgentLifecycleEmailRecipient(email=e, full_name=None) for e in recipients]
        self._notified = already_notified or set()
        self.recorded: list[str] = []

    def find_lifecycle_email_recipients(self, agent_id, organization_id):
        return self._recipients

    def find_notified_lifecycle_email_recipients(self, delivery_id):
        return self._notified

    def record_lifecycle_email_recipient_notified(self, delivery_id, recipient_email):
        self.recorded.append(recipient_email)


class _FakeEmailService:
    def __init__(self, failures: dict[str, Exception] | None = None):
        self._failures = failures or {}
        self.attempted: list[str] = []

    def send_agent_lifecycle_email(self, *, receiver_email, receiver_name, agent_name, lifecycle_action):
        self.attempted.append(receiver_email)
        failure = self._failures.get(receiver_email)
        if failure is not None:
            raise failure


def _handler(repository: _FakeRepository, email_service: _FakeEmailService) -> AgentLifecycleEmailHandler:
    return AgentLifecycleEmailHandler(
        repository=cast(AgentRepository, repository),
        email_service=cast(EmailService, email_service),
    )


def _event_and_context():
    actor = ActorIdentity(type=ActorIdentityType.USER, id=uuid4(), organization_id=ORG_ID)
    event = DomainEventEnvelope(
        event_name=AGENT_STARTED,
        schema_version=1,
        event_scope=EventScope.ORGANIZATION,
        organization_id=ORG_ID,
        occurred_at=datetime.now(UTC),
        actor=actor,
        subject=SubjectIdentity(type=SubjectIdentityType.AGENT, id=AGENT_ID, organization_id=ORG_ID),
        correlation_id=uuid4(),
        payload={"agent_id": str(AGENT_ID), "agent_name": "watcher"},
    )
    context = EventDeliveryContext(
        delivery_id=DELIVERY_ID,
        event_id=event.event_id,
        handler_name=AGENT_LIFECYCLE_EMAIL_HANDLER,
        attempt_count=1,
        correlation_id=event.correlation_id,
        organization_id=ORG_ID,
    )
    return event, context


def test_retryable_send_failure_reschedules_the_delivery():
    repository = _FakeRepository(["a@example.com"])
    service = _FakeEmailService({"a@example.com": RetryableEmailSendingException("429", email="a@example.com")})
    event, context = _event_and_context()

    assert_that(
        calling(_handler(repository, service).handle).with_args(event, context),
        raises(RetryableEventHandlerError),
    )
    assert_that(repository.recorded, empty())


def test_terminal_send_failure_dead_letters_instead_of_burning_retries():
    repository = _FakeRepository(["a@example.com"])
    service = _FakeEmailService({"a@example.com": TerminalEmailSendingException("400", email="a@example.com")})
    event, context = _event_and_context()

    assert_that(
        calling(_handler(repository, service).handle).with_args(event, context),
        raises(TerminalEventHandlerError),
    )
    assert_that(repository.recorded, empty())


def test_retryable_wins_when_failures_are_mixed():
    # Rescheduling rescues the transient recipient; the terminal one is re-classified on
    # the next attempt rather than being retried indefinitely.
    repository = _FakeRepository(["transient@example.com", "bad@example.com"])
    service = _FakeEmailService(
        {
            "transient@example.com": RetryableEmailSendingException("500", email="transient@example.com"),
            "bad@example.com": TerminalEmailSendingException("400", email="bad@example.com"),
        }
    )
    event, context = _event_and_context()

    assert_that(
        calling(_handler(repository, service).handle).with_args(event, context),
        raises(RetryableEventHandlerError),
    )


def test_successful_recipients_are_recorded_even_when_another_fails():
    repository = _FakeRepository(["ok@example.com", "bad@example.com"])
    service = _FakeEmailService({"bad@example.com": RetryableEmailSendingException("500", email="bad@example.com")})
    event, context = _event_and_context()

    assert_that(
        calling(_handler(repository, service).handle).with_args(event, context),
        raises(RetryableEventHandlerError),
    )
    # The retry must not re-send to the recipient that already succeeded.
    assert_that(repository.recorded, equal_to(["ok@example.com"]))


def test_already_notified_recipients_are_skipped_on_retry():
    repository = _FakeRepository(["done@example.com", "pending@example.com"], already_notified={"done@example.com"})
    service = _FakeEmailService()
    event, context = _event_and_context()

    _handler(repository, service).handle(event, context)

    assert_that(service.attempted, equal_to(["pending@example.com"]))
    assert_that(repository.recorded, equal_to(["pending@example.com"]))


def test_all_recipients_sent_raises_nothing():
    repository = _FakeRepository(["a@example.com", "b@example.com"])
    service = _FakeEmailService()
    event, context = _event_and_context()

    _handler(repository, service).handle(event, context)

    assert_that(repository.recorded, equal_to(["a@example.com", "b@example.com"]))
