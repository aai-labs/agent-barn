"""Owners and Admins are emailed about unusual activity worth a look (AF-464).

The contract under test, end to end from a real check's alert Event through the real
handler wiring, with only the mail client faked:

- Owners and Admins are emailed, Members are not, matching who may see unusual activity;
- the email names the Agent, what was flagged, how it was classified, and links to the
  Agent's Unusual activity tab;
- low severity and probably-fine activity is not emailed;
- activity that could not be classified waits while classification may still be
  running, then is emailed as not classified;
- a retry does not email anyone twice, and a failed send is retried;
- Hermes and OpenClaw Agents are alike.
"""

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa
from hamcrest import (
    assert_that,
    calling,
    contains_inanyorder,
    contains_string,
    empty,
    equal_to,
    has_length,
    is_not,
    raises,
)
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentType
from api.domains.anomalies.event_handlers import AnomalyAlertEmailHandler
from api.domains.anomalies.models import AgentAnomaly
from api.domains.events.catalog import AGENT_ANOMALY_ALERT_EMAIL_HANDLER, AGENT_ANOMALY_FLAGGED
from api.domains.events.handlers import EventDeliveryContext, EventHandlerRegistry, RetryableEventHandlerError
from api.domains.events.models import (
    ActorIdentity,
    DomainEventEnvelope,
    EventDelivery,
    OutboxMessage,
    SubjectIdentity,
)
from api.domains.rbac.catalog import OrganizationRole
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationUser
from api.infrastructure.email.client import EmailClient
from api.infrastructure.email.models import Email
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.integration.test_anomaly_checks import _check
from api.tests.integration.test_anomaly_classification_checks import (
    _a_tool_call_spike,
    _given,
    the_decision_model_classifies,
    the_decision_model_fails,
)
from api.tests.steps.user import there_is_a_user

ADMIN = "admin@example.com"
MEMBER = "member@example.com"


def the_organization_has_an_admin_and_a_member():
    def step(context):
        user = context.user
        there_is_a_user(email=ADMIN, role=OrganizationRole.ADMIN)(context)
        there_is_a_user(email=MEMBER, role=OrganizationRole.MEMBER)(context)
        context.user = user

    return step


def _owner_email(context) -> str:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return session.exec(
            select(User.email)
            .join(OrganizationUser, col(OrganizationUser.user_id) == col(User.id))
            .where(
                col(OrganizationUser.organization_id) == context.agent.organization_id,
                col(OrganizationUser.role) == OrganizationRole.OWNER,
            )
        ).one()


@pytest.fixture
def sent(monkeypatch) -> list[Email]:
    emails: list[Email] = []

    def fake_send(self, email: Email) -> Email:
        emails.append(email)
        return email

    monkeypatch.setattr(EmailClient, "send", fake_send)
    return emails


def _delivery(context) -> tuple[DomainEventEnvelope, EventDeliveryContext]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        message = session.exec(
            select(OutboxMessage).where(col(OutboxMessage.event_name) == AGENT_ANOMALY_FLAGGED)
        ).one()
        delivery = session.exec(
            select(EventDelivery).where(
                col(EventDelivery.event_id) == message.event_id,
                col(EventDelivery.handler_name) == AGENT_ANOMALY_ALERT_EMAIL_HANDLER,
            )
        ).one()
    event = DomainEventEnvelope(
        event_id=message.event_id,
        event_name=message.event_name,
        schema_version=message.schema_version,
        occurred_at=message.occurred_at,
        event_scope=message.event_scope,
        organization_id=message.organization_id,
        actor=ActorIdentity.model_validate(message.actor),
        subject=SubjectIdentity.model_validate(message.subject),
        correlation_id=message.correlation_id,
        causation_id=message.causation_id,
        payload=message.payload,
    )
    return event, EventDeliveryContext(
        delivery_id=delivery.id,
        event_id=message.event_id,
        handler_name=AGENT_ANOMALY_ALERT_EMAIL_HANDLER,
        attempt_count=1,
        correlation_id=message.correlation_id,
        organization_id=message.organization_id,
    )


def _deliver(context) -> None:
    context.injector.get(AnomalyAlertEmailHandler).handle(*_delivery(context))


def _flag_a_spike(context) -> None:
    _a_tool_call_spike(context)
    _check(context)


def _anomalies_were_created(context, ago: timedelta) -> None:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        session.exec(
            sa.update(AgentAnomaly)  # type: ignore[call-overload]
            .where(col(AgentAnomaly.agent_id) == context.agent.id)
            .values(created_at=datetime.now(UTC) - ago)
        )
        session.commit()


@pytest.mark.parametrize("agent_type", [AgentType.OPENCLAW, AgentType.HERMES])
def test_owners_and_admins_are_emailed_what_was_flagged_and_how_it_was_classified(sent, agent_type):
    with given(
        _given(
            the_decision_model_classifies(unusual=0.9, category="RUNAWAY_LOOP", score=2.0),
            the_organization_has_an_admin_and_a_member(),
            agent_type=agent_type,
        )
    ) as context:
        _flag_a_spike(context)

        _deliver(context)

        assert_that([email.to_email for email in sent], contains_inanyorder(_owner_email(context), ADMIN))
        email = sent[0]
        assert_that(email.subject, contains_string(context.agent.name))
        assert_that(email.html_part, contains_string("Tool calls per hour"))
        assert_that(email.html_part, contains_string("Runaway loop, high severity"))
        assert_that(
            email.html_part,
            contains_string(
                f"/dashboard/{context.agent.organization_id}/agents/{context.agent.id}?tab=unusual-activity"
            ),
        )


@pytest.mark.parametrize(
    ("unusual", "score"),
    [pytest.param(0.9, 0.0, id="low severity"), pytest.param(0.3, 3.0, id="probably fine")],
)
def test_low_severity_and_probably_fine_activity_is_not_emailed(sent, unusual, score):
    with given(_given(the_decision_model_classifies(unusual=unusual, score=score))) as context:
        _flag_a_spike(context)

        _deliver(context)

        assert_that(sent, empty())


def test_unclassified_activity_waits_while_it_may_still_be_classified(sent):
    with given(_given(the_decision_model_fails())) as context:
        _flag_a_spike(context)

        assert_that(calling(_deliver).with_args(context), raises(RetryableEventHandlerError))
        assert_that(sent, empty())


def test_unclassified_activity_is_emailed_as_not_classified_once_it_has_had_its_chance(sent):
    with given(_given(the_decision_model_fails())) as context:
        _flag_a_spike(context)
        _anomalies_were_created(context, ago=timedelta(minutes=10))

        _deliver(context)

        assert_that(sent, has_length(1))
        assert_that(sent[0].html_part, contains_string("Not classified"))
        assert_that(sent[0].html_part, is_not(contains_string("Runaway loop")))


def test_a_retry_does_not_email_anyone_twice(sent):
    with given(_given(the_decision_model_classifies(), the_organization_has_an_admin_and_a_member())) as context:
        _flag_a_spike(context)

        _deliver(context)
        _deliver(context)

        assert_that(sent, has_length(2))


def test_a_failed_send_is_retried(monkeypatch):
    def failing_send(self, email: Email) -> Email:
        raise RuntimeError("mail provider down")

    monkeypatch.setattr(EmailClient, "send", failing_send)
    with given(_given(the_decision_model_classifies())) as context:
        _flag_a_spike(context)

        assert_that(calling(_deliver).with_args(context), raises(RetryableEventHandlerError))


def test_nobody_is_emailed_about_an_agent_deleted_since(sent):
    with given(_given(the_decision_model_classifies())) as context:
        _flag_a_spike(context)
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            agent = session.get(Agent, context.agent.id)
            assert agent is not None
            agent.deleted_at = datetime.now(UTC)
            session.add(agent)
            session.commit()

        _deliver(context)

        assert_that(sent, equal_to([]))


def test_the_workers_registry_delivers_alert_events_to_the_handler():
    """Without it, a worker dead-letters every alert as an unknown handler."""
    with given(_given()) as context:
        registry = context.injector.get(EventHandlerRegistry)

        assert_that(registry.supports(AGENT_ANOMALY_ALERT_EMAIL_HANDLER, AGENT_ANOMALY_FLAGGED, 1), equal_to(True))
