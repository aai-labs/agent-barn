"""Linking a Telegram account through the shared bot records telegram.account.linked, and
a link it replaces records telegram.account.unlinked (relinked). Both are attributed to the
Member who created the link, in that link's Organization, and carry no Telegram identity."""

import json
import threading
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from hamcrest import assert_that, contains_string, equal_to, has_length, is_not
from sqlmodel import Session, col, select

from api.domains.communications.agentbarn_telegram_repository import AgentBarnTelegramRepository
from api.domains.communications.agentbarn_telegram_service import AgentBarnTelegramService, hash_link_token
from api.domains.communications.models import CommunicationConnection
from api.domains.events.catalog import PRODUCT_ANALYTICS_HANDLER, TELEGRAM_ACCOUNT_LINKED, TELEGRAM_ACCOUNT_UNLINKED
from api.domains.events.dispatch import EventDeliveryDispatcher
from api.domains.events.models import EventDelivery, EventScope, OutboxMessage
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.telegram_link_events import unlink_reasons, unlinked_events

_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
_TELEGRAM_USER = 5550001
_TELEGRAM_USERNAME = "jane_doe_telegram"


def _agent_with_connection(key: str, name: str):
    def step(context):
        there_is_an_agent(name=name)(context)
        connection = CommunicationConnection(
            organization_id=context.agent.organization_id,
            agent_id=context.agent.id,
            platform_key="agentbarn_telegram",
            display_name="Agent Barn Telegram",
            credentials_encrypted="unused",
        )
        context.injector.get(PostgresRepositoryDelegate).save(connection)
        setattr(context, key, connection)
        setattr(context, f"{key}_membership", context.organization_user)

    return step


_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    _agent_with_connection("first", "First Agent"),
    _agent_with_connection("second", "Second Agent"),
]


def _repo(context) -> AgentBarnTelegramRepository:
    return context.injector.get(AgentBarnTelegramRepository)


def _token(context, connection: CommunicationConnection, raw: str, membership, *, expires_at=None):
    return _repo(context).create_link_token(
        organization_id=connection.organization_id,
        agent_id=connection.agent_id,
        connection_id=connection.id,
        requested_by_membership_id=membership.id,
        token_hash=hash_link_token(raw),
        expires_at=expires_at or _NOW + timedelta(minutes=10),
    )


def _consume(context, raw: str, *, now: datetime = _NOW):
    return _repo(context).consume_link_token(
        hash_link_token(raw), telegram_user_id=_TELEGRAM_USER, telegram_username=_TELEGRAM_USERNAME, now=now
    )


def _events(context, event_name: str) -> list[OutboxMessage]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(
            session.exec(
                select(OutboxMessage)
                .where(col(OutboxMessage.event_name) == event_name)
                .order_by(col(OutboxMessage.occurred_at))
            )
        )


def _delivery_ids(context, event: OutboxMessage) -> list:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(session.exec(select(EventDelivery.id).where(col(EventDelivery.event_id) == event.event_id)))


def _handlers(context, event: OutboxMessage) -> list[str]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(
            session.exec(select(EventDelivery.handler_name).where(col(EventDelivery.event_id) == event.event_id))
        )


def _assert_no_telegram_identity(event: OutboxMessage) -> None:
    serialized = json.dumps(event.payload)
    assert_that(serialized, is_not(contains_string(str(_TELEGRAM_USER))))
    assert_that(serialized, is_not(contains_string(_TELEGRAM_USERNAME)))


def test_linking_records_a_linked_event_as_the_member_who_created_the_link():
    with given(_GIVEN) as context:
        _token(context, context.first, "raw-1", context.first_membership)

        result = _consume(context, "raw-1")

        assert result.link is not None
        events = _events(context, TELEGRAM_ACCOUNT_LINKED)
        assert_that(events, has_length(1))
        event = events[0]
        assert_that(
            (event.event_scope, event.organization_id, event.actor, event.subject, event.payload),
            equal_to(
                (
                    EventScope.ORGANIZATION,
                    context.first.organization_id,
                    {
                        "type": "MEMBERSHIP",
                        "id": str(context.first_membership.id),
                        "organization_id": str(context.first.organization_id),
                    },
                    {
                        "type": "AGENT",
                        "id": str(context.first.agent_id),
                        "organization_id": str(context.first.organization_id),
                    },
                    {
                        "organization_id": str(context.first.organization_id),
                        "agent_id": str(context.first.agent_id),
                        "connection_id": str(context.first.id),
                        "link_id": str(result.link.id),
                    },
                )
            ),
        )
        _assert_no_telegram_identity(event)
        assert_that(_handlers(context, event), equal_to([PRODUCT_ANALYTICS_HANDLER]))
        assert_that(sorted(result.delivery_ids), equal_to(sorted(_delivery_ids(context, event))))
        assert_that(_events(context, TELEGRAM_ACCOUNT_UNLINKED), equal_to([]))


def test_a_replaced_link_records_a_relinked_unlink_for_the_old_link():
    with given(_GIVEN) as context:
        _token(context, context.first, "raw-1", context.first_membership)
        _token(context, context.second, "raw-2", context.second_membership)
        first = _consume(context, "raw-1")

        second = _consume(context, "raw-2", now=_NOW + timedelta(minutes=1))

        assert first.link is not None
        unlinked = _events(context, TELEGRAM_ACCOUNT_UNLINKED)
        assert_that(unlinked, has_length(1))
        assert_that(
            unlinked[0].payload,
            equal_to(
                {
                    "organization_id": str(context.first.organization_id),
                    "agent_id": str(context.first.agent_id),
                    "connection_id": str(context.first.id),
                    "link_id": str(first.link.id),
                    "reason": "relinked",
                }
            ),
        )
        _assert_no_telegram_identity(unlinked[0])
        assert_that(_events(context, TELEGRAM_ACCOUNT_LINKED), has_length(2))
        assert_that(len(second.delivery_ids), equal_to(2))


def test_a_link_replaced_from_another_organization_is_recorded_in_its_own_organization():
    with given(
        [
            *_GIVEN,
            there_is_an_organization_with_user_and_access_token(),
            _agent_with_connection("other", "Other Organization Agent"),
        ]
    ) as context:
        _token(context, context.first, "raw-1", context.first_membership)
        _token(context, context.other, "raw-other", context.other_membership)
        _consume(context, "raw-1")

        _consume(context, "raw-other", now=_NOW + timedelta(minutes=1))

        unlinked = _events(context, TELEGRAM_ACCOUNT_UNLINKED)
        assert_that(unlinked, has_length(1))
        assert_that(
            (unlinked[0].organization_id, unlinked[0].actor),
            equal_to(
                (
                    context.first.organization_id,
                    {
                        "type": "MEMBERSHIP",
                        "id": str(context.first_membership.id),
                        "organization_id": str(context.first.organization_id),
                    },
                )
            ),
        )
        linked = _events(context, TELEGRAM_ACCOUNT_LINKED)
        assert_that(
            [event.organization_id for event in linked],
            equal_to([context.first.organization_id, context.other.organization_id]),
        )


def test_a_refused_token_records_nothing():
    with given(_GIVEN) as context:
        _token(context, context.first, "raw-expired", context.first_membership, expires_at=_NOW - timedelta(minutes=1))
        _token(context, context.second, "raw-used", context.second_membership)
        _consume(context, "raw-used")
        before = len(_events(context, TELEGRAM_ACCOUNT_LINKED))

        _consume(context, "raw-expired")
        _consume(context, "raw-never-issued")
        _consume(context, "raw-used")

        assert_that(len(_events(context, TELEGRAM_ACCOUNT_LINKED)), equal_to(before))
        assert_that(_events(context, TELEGRAM_ACCOUNT_UNLINKED), equal_to([]))


def test_racing_first_links_record_each_link_once():
    with given(_GIVEN) as context:
        _token(context, context.first, "raw-1", context.first_membership)
        _token(context, context.second, "raw-2", context.second_membership)
        barrier = threading.Barrier(2)

        def consume(raw: str) -> None:
            barrier.wait()
            _consume(context, raw)

        threads = [threading.Thread(target=consume, args=(raw,)) for raw in ("raw-1", "raw-2")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        assert_that(_events(context, TELEGRAM_ACCOUNT_LINKED), has_length(2))
        assert_that(_events(context, TELEGRAM_ACCOUNT_UNLINKED), has_length(1))


def test_the_bot_enqueues_the_link_events_it_staged():
    with given(_GIVEN) as context:
        _token(
            context,
            context.first,
            "raw-1",
            context.first_membership,
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )

        with patch.object(EventDeliveryDispatcher, "enqueue_immediate") as enqueue:
            result = context.injector.get(AgentBarnTelegramService).consume_link_token(
                "raw-1", telegram_user_id=_TELEGRAM_USER, telegram_username=_TELEGRAM_USERNAME
            )

        enqueue.assert_called_once_with(list(result.delivery_ids))
        assert_that(result.delivery_ids, has_length(1))


def test_ending_an_active_link_records_its_reason_as_its_linker():
    with given(_GIVEN) as context:
        _token(context, context.first, "raw-1", context.first_membership)
        link = _consume(context, "raw-1").link
        assert link is not None

        delivery_ids = _repo(context).end_active_link(_TELEGRAM_USER, now=_NOW, reason="blocked_bot")

        events = unlinked_events(context)
        assert_that(unlink_reasons(context), equal_to(["blocked_bot"]))
        assert_that(
            (events[0].organization_id, events[0].actor["id"], events[0].payload["link_id"]),
            equal_to((context.first.organization_id, str(context.first_membership.id), str(link.id))),
        )
        _assert_no_telegram_identity(events[0])
        assert_that(sorted(delivery_ids), equal_to(sorted(_delivery_ids(context, events[0]))))


def test_ending_a_connections_link_records_its_reason():
    with given(_GIVEN) as context:
        _token(context, context.first, "raw-1", context.first_membership)
        _consume(context, "raw-1")

        delivery_ids = _repo(context).end_link_for_connection(
            context.first.id, _TELEGRAM_USER, now=_NOW, reason="access_lost"
        )

        assert_that(unlink_reasons(context), equal_to(["access_lost"]))
        assert_that(delivery_ids, has_length(1))


def test_ending_a_link_that_already_ended_records_nothing():
    with given(_GIVEN) as context:
        _token(context, context.first, "raw-1", context.first_membership)
        _consume(context, "raw-1")
        _repo(context).end_active_link(_TELEGRAM_USER, now=_NOW, reason="blocked_bot")

        again = _repo(context).end_active_link(_TELEGRAM_USER, now=_NOW, reason="blocked_bot")
        for_connection = _repo(context).end_link_for_connection(
            context.first.id, _TELEGRAM_USER, now=_NOW, reason="access_lost"
        )

        assert_that((again, for_connection), equal_to(((), ())))
        assert_that(unlink_reasons(context), equal_to(["blocked_bot"]))
