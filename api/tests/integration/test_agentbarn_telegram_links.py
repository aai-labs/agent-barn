from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from hamcrest import assert_that, contains_exactly, equal_to, has_properties, is_, none, not_none
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.communications.agentbarn_telegram_repository import (
    AgentBarnTelegramRepository,
    LinkTokenOutcome,
)
from api.domains.communications.models import (
    AgentBarnTelegramLink,
    AgentBarnTelegramLinkToken,
    CommunicationConnection,
)
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
_TELEGRAM_USER = 5550001


def _agent_with_connection(key: str, name: str):
    """An Agent with an Agent Barn Telegram Connection, stored on the context under `key`."""

    def step(context):
        there_is_an_agent(name=name)(context)
        connection = CommunicationConnection(
            organization_id=context.agent.organization_id,
            agent_id=context.agent.id,
            platform_key="agentbarn_telegram",
            display_name="Agent Barn Telegram",
            credentials_encrypted="unused",
            driver_key_encrypted="unused",
        )
        context.injector.get(PostgresRepositoryDelegate).save(connection)
        setattr(context, key, connection)

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


def _scope(context) -> AuthorizationScope:
    return AuthorizationScope(organization_id=context.organization.id)


def _token(context, connection: CommunicationConnection, token_hash: str, *, expires_at=None):
    return _repo(context).create_link_token(
        organization_id=connection.organization_id,
        agent_id=connection.agent_id,
        connection_id=connection.id,
        requested_by_membership_id=context.organization_user.id,
        token_hash=token_hash,
        expires_at=expires_at or _NOW + timedelta(minutes=10),
    )


def _consume(context, token_hash: str, *, user: int = _TELEGRAM_USER, now: datetime = _NOW):
    return _repo(context).consume_link_token(token_hash, telegram_user_id=user, telegram_username="jane_doe", now=now)


def _links(context) -> list[AgentBarnTelegramLink]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(session.exec(select(AgentBarnTelegramLink).order_by(col(AgentBarnTelegramLink.created_at))))


def test_a_valid_token_links_the_telegram_user_to_the_agent() -> None:
    with given(_GIVEN) as context:
        token = _token(context, context.first, "hash-1")

        with when("the Telegram user presents the token"):
            result = _consume(context, "hash-1")

        with then("the user is linked to that Agent by the member who asked, and the token is spent"):
            assert_that(result.outcome, equal_to(LinkTokenOutcome.LINKED))
            assert_that(
                result.link,
                has_properties(
                    agent_id=context.first.agent_id,
                    connection_id=context.first.id,
                    telegram_user_id=_TELEGRAM_USER,
                    telegram_username="jane_doe",
                    linked_by_membership_id=context.organization_user.id,
                    unlinked_at=none(),
                ),
            )
            assert_that(result.replaced_link, is_(none()))
            spent = _repo(context).get_link_token_in_scope(
                token.id, context.first.id, context.first.agent_id, _scope(context)
            )
            assert_that(spent, has_properties(consumed_at=not_none(), link_id=result.link.id))


def test_a_token_links_only_once() -> None:
    with given(_GIVEN) as context:
        _token(context, context.first, "hash-1")

        with when("the token is presented twice, the second time by someone else"):
            _consume(context, "hash-1")
            second = _consume(context, "hash-1", user=5550002)

        with then("the second attempt is refused and only the first user is linked"):
            assert_that(second.outcome, equal_to(LinkTokenOutcome.INVALID))
            assert_that([link.telegram_user_id for link in _links(context)], contains_exactly(_TELEGRAM_USER))


def test_an_expired_token_links_nobody() -> None:
    with given(_GIVEN) as context:
        _token(context, context.first, "hash-1", expires_at=_NOW - timedelta(seconds=1))

        with when("the Telegram user presents an expired token"):
            result = _consume(context, "hash-1")

        with then("it is reported as expired and nothing is linked"):
            assert_that(result.outcome, equal_to(LinkTokenOutcome.EXPIRED))
            assert_that(_links(context), equal_to([]))


def test_an_unknown_token_links_nobody() -> None:
    with given(_GIVEN) as context:
        with when("the Telegram user presents a token that was never issued"):
            result = _consume(context, "never-issued")

        with then("it is refused"):
            assert_that(result.outcome, equal_to(LinkTokenOutcome.INVALID))
            assert_that(_links(context), equal_to([]))


@pytest.mark.parametrize("change", ["retired", "disabled"])
def test_a_token_for_a_connection_no_longer_in_use_links_nobody(change: str) -> None:
    with given(_GIVEN) as context:
        _token(context, context.first, "hash-1")
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            connection = session.get(CommunicationConnection, context.first.id)
            assert connection is not None
            if change == "retired":
                connection.retired_at = _NOW
            else:
                connection.enabled = False
            session.add(connection)
            session.commit()

        with when("the Telegram user presents the token"):
            result = _consume(context, "hash-1")

        with then("it is refused"):
            assert_that(result.outcome, equal_to(LinkTokenOutcome.INVALID))
            assert_that(_links(context), equal_to([]))


def test_linking_a_second_agent_replaces_the_first_link() -> None:
    with given(_GIVEN) as context:
        _token(context, context.first, "hash-1")
        _token(context, context.second, "hash-2")

        with when("the same Telegram user links the first Agent, then the second"):
            first = _consume(context, "hash-1")
            second = _consume(context, "hash-2", now=_NOW + timedelta(minutes=1))

        with then("only the second link is active and the result names the one it replaced"):
            assert_that(second.outcome, equal_to(LinkTokenOutcome.LINKED))
            assert first.link is not None
            assert_that(second.replaced_link, has_properties(id=first.link.id, agent_id=context.first.agent_id))
            assert_that(
                [(link.agent_id, link.unlinked_at) for link in _links(context)],
                equal_to(
                    [
                        (context.first.agent_id, _NOW + timedelta(minutes=1)),
                        (context.second.agent_id, None),
                    ]
                ),
            )


def test_a_telegram_user_cannot_hold_two_active_links() -> None:
    with given(_GIVEN) as context:
        delegate = context.injector.get(PostgresRepositoryDelegate)

        def link(connection: CommunicationConnection) -> AgentBarnTelegramLink:
            return AgentBarnTelegramLink(
                organization_id=connection.organization_id,
                agent_id=connection.agent_id,
                connection_id=connection.id,
                telegram_user_id=_TELEGRAM_USER,
                linked_by_membership_id=context.organization_user.id,
            )

        delegate.save(link(context.first))

        with then("the database refuses a second active link for the same Telegram user"):
            with pytest.raises(IntegrityError):
                delegate.save(link(context.second))


def test_active_links_are_listed_per_connection_and_within_scope() -> None:
    with given(_GIVEN) as context:
        _token(context, context.first, "hash-1")
        _token(context, context.second, "hash-2")
        _consume(context, "hash-1")
        _consume(context, "hash-2", user=5550002)

        with when("I list the first Connection's links in my Organization and in another one"):
            mine = _repo(context).list_active_links_in_scope(context.first.id, context.first.agent_id, _scope(context))
            elsewhere = _repo(context).list_active_links_in_scope(
                context.first.id, context.first.agent_id, AuthorizationScope(organization_id=uuid4())
            )

        with then("only that Connection's link is visible, and only in my Organization"):
            assert_that([link.telegram_user_id for link in mine], contains_exactly(_TELEGRAM_USER))
            assert_that(elsewhere, equal_to([]))


def test_unlinking_ends_the_link_once_and_only_within_scope() -> None:
    with given(_GIVEN) as context:
        _token(context, context.first, "hash-1")
        link = _consume(context, "hash-1").link
        args = (link.id, context.first.id, context.first.agent_id)

        with when("someone outside the Organization tries to unlink it, then I unlink it twice"):
            outsider = _repo(context).unlink_in_scope(*args, AuthorizationScope(organization_id=uuid4()), now=_NOW)
            first = _repo(context).unlink_in_scope(*args, _scope(context), now=_NOW)
            again = _repo(context).unlink_in_scope(*args, _scope(context), now=_NOW)

        with then("only my first unlink takes effect"):
            assert_that((outsider, first, again), equal_to((False, True, False)))
            assert_that(_links(context)[0].unlinked_at, equal_to(_NOW))
            assert_that(
                _repo(context).list_active_links_in_scope(context.first.id, context.first.agent_id, _scope(context)),
                equal_to([]),
            )


def test_a_link_token_is_read_only_through_its_own_connection_and_scope() -> None:
    with given(_GIVEN) as context:
        token = _token(context, context.first, "hash-1")

        with when("I read the token through its Connection, another Connection, and another Organization"):
            own = _repo(context).get_link_token_in_scope(
                token.id, context.first.id, context.first.agent_id, _scope(context)
            )
            other_connection = _repo(context).get_link_token_in_scope(
                token.id, context.second.id, context.second.agent_id, _scope(context)
            )
            other_org = _repo(context).get_link_token_in_scope(
                token.id, context.first.id, context.first.agent_id, AuthorizationScope(organization_id=uuid4())
            )

        with then("only the first read finds it"):
            assert_that(own, has_properties(id=token.id, token_hash="hash-1"))
            assert_that((other_connection, other_org), equal_to((None, None)))
            assert_that(isinstance(own, AgentBarnTelegramLinkToken), is_(True))
