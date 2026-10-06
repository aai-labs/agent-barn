from datetime import UTC, datetime, timedelta

from hamcrest import assert_that, contains_exactly, contains_string, equal_to, has_properties, is_, none, not_none
from sqlmodel import Session, col, select

from api.domains.communications.agentbarn_telegram_processor import AgentBarnTelegramUpdateProcessor
from api.domains.communications.agentbarn_telegram_repository import AgentBarnTelegramRepository
from api.domains.communications.agentbarn_telegram_service import hash_link_token
from api.domains.communications.models import (
    AgentBarnTelegramLink,
    AgentBarnTelegramUpdate,
    AgentBarnTelegramUpdateStatus,
    CommunicationConnection,
)
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_JANE = 5550001
_WEB_APP_URL = "https://app.agentbarn.test"


class RecordingBot:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[int, str]] = []
        self.fail = fail

    def send(self, chat_id: int, text: str) -> None:
        if self.fail:
            raise RuntimeError("Telegram is down")
        self.sent.append((chat_id, text))


def _agent_with_connection(key: str, name: str):
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


def _recording_bot(context) -> None:
    context.bot = RecordingBot()
    context.injector.get(AgentBarnTelegramUpdateProcessor).bot = context.bot


_GIVEN = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY, "WEB_APP_URL": _WEB_APP_URL}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    _agent_with_connection("sales", "Sales Helper"),
    _agent_with_connection("support", "Support Desk"),
    _recording_bot,
]


def _repo(context) -> AgentBarnTelegramRepository:
    return context.injector.get(AgentBarnTelegramRepository)


def _issue(context, connection: CommunicationConnection, raw: str, *, expires_in=timedelta(minutes=10)) -> None:
    _repo(context).create_link_token(
        organization_id=connection.organization_id,
        agent_id=connection.agent_id,
        connection_id=connection.id,
        requested_by_membership_id=context.organization_user.id,
        token_hash=hash_link_token(raw),
        expires_at=datetime.now(UTC) + expires_in,
    )


_next_update_id = iter(range(1000, 10_000))


def _receive(context, update: dict) -> int:
    update_id = next(_next_update_id)
    _repo(context).store_updates([{**update, "update_id": update_id}])
    context.injector.get(AgentBarnTelegramUpdateProcessor).process_pending()
    return update_id


def _private(text: str, user: int = _JANE, first_name: str = "Jane") -> dict:
    sender = {"id": user, "is_bot": False, "first_name": first_name, "username": "jane_doe"}
    return {
        "message": {"message_id": 1, "from": sender, "chat": {"id": user, "type": "private"}, "date": 0, "text": text}
    }


def _stored(context, update_id: int) -> AgentBarnTelegramUpdate:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return session.exec(
            select(AgentBarnTelegramUpdate).where(col(AgentBarnTelegramUpdate.update_id) == update_id)
        ).one()


def _active_links(context) -> list[AgentBarnTelegramLink]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(session.exec(select(AgentBarnTelegramLink).where(col(AgentBarnTelegramLink.unlinked_at).is_(None))))


def test_starting_the_bot_with_a_link_connects_the_user_and_greets_them() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")

        with when("Jane presses Start on her link"):
            update_id = _receive(context, _private("/start token-sales"))

        with then("she is linked to the agent and greeted by name, and nothing is kept of the message"):
            assert_that([link.agent_id for link in _active_links(context)], contains_exactly(context.sales.agent_id))
            assert_that(
                context.bot.sent,
                contains_exactly((_JANE, "Hi Jane! You're linked to Sales Helper. Send a message to get started.")),
            )
            assert_that(
                _stored(context, update_id),
                has_properties(status=AgentBarnTelegramUpdateStatus.HANDLED, payload=none()),
            )


def test_linking_another_agent_tells_the_user_they_switched() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")
        _issue(context, context.support, "token-support")
        _receive(context, _private("/start token-sales"))

        with when("Jane links the second agent"):
            _receive(context, _private("/start token-support"))

        with then("she is told who she now talks to and who she no longer hears from"):
            assert_that(
                context.bot.sent[-1],
                equal_to(
                    (
                        _JANE,
                        "You're now talking to Support Desk. You won't get replies from Sales Helper here anymore.",
                    )
                ),
            )


def test_an_expired_link_asks_for_a_fresh_one() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-old", expires_in=timedelta(seconds=-1))

        with when("Jane presses Start on an expired link"):
            _receive(context, _private("/start token-old"))

        with then("she is asked to get a fresh one and nothing is linked"):
            assert_that(
                context.bot.sent,
                contains_exactly((_JANE, "This link has expired. Go back to Agent Barn for a fresh one.")),
            )
            assert_that(_active_links(context), equal_to([]))


def test_a_used_or_unknown_link_asks_for_a_fresh_one() -> None:
    with given(_GIVEN) as context:
        with when("Jane presses Start on a link that was never issued"):
            _receive(context, _private("/start never-issued"))

        with then("she is told it is not valid"):
            assert_that(
                context.bot.sent,
                contains_exactly(
                    (_JANE, "This link has already been used or isn't valid. Go back to Agent Barn for a fresh one.")
                ),
            )


def test_a_stranger_is_pointed_to_sign_up_and_reaches_no_agent() -> None:
    with given(_GIVEN) as context:
        with when("someone who never linked writes to the bot"):
            update_id = _receive(context, _private("hello?", user=7770007, first_name="Sam"))

        with then("they are pointed to sign up and the message is not kept"):
            assert_that(
                context.bot.sent,
                contains_exactly(
                    (
                        7770007,
                        f"Hi! To talk to an agent here, sign up at {_WEB_APP_URL} and connect Telegram from there.",
                    )
                ),
            )
            assert_that(_stored(context, update_id), has_properties(status=AgentBarnTelegramUpdateStatus.HANDLED))


def test_a_linked_users_message_is_queued_for_their_agent() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")
        _receive(context, _private("/start token-sales"))
        greeted = len(context.bot.sent)

        with when("Jane writes to her agent"):
            update_id = _receive(context, _private("What's on today?"))

        with then("the message waits for her agent, with its content, and the bot itself stays quiet"):
            assert_that(
                _stored(context, update_id),
                has_properties(
                    status=AgentBarnTelegramUpdateStatus.QUEUED,
                    agent_id=context.sales.agent_id,
                    connection_id=context.sales.id,
                    telegram_user_id=_JANE,
                    payload=not_none(),
                ),
            )
            assert_that(len(context.bot.sent), equal_to(greeted))


def test_a_user_whose_linker_lost_access_is_unlinked() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")
        _receive(context, _private("/start token-sales"))
        context.organization_user.role = OrganizationRole.MEMBER
        context.injector.get(OrganizationUserRepository).save(context.organization_user)

        with when("Jane writes after the member who linked her lost access to the agent"):
            update_id = _receive(context, _private("still there?"))

        with then("her link ends, the message reaches no agent, and she is pointed to sign up"):
            assert_that(_active_links(context), equal_to([]))
            assert_that(_stored(context, update_id), has_properties(status=AgentBarnTelegramUpdateStatus.HANDLED))
            assert_that(context.bot.sent[-1][1], contains_string("sign up at"))


def test_blocking_the_bot_ends_the_link_silently() -> None:
    with given(_GIVEN) as context:
        _issue(context, context.sales, "token-sales")
        _receive(context, _private("/start token-sales"))
        sent_before = len(context.bot.sent)
        blocked = {
            "my_chat_member": {
                "chat": {"id": _JANE, "type": "private"},
                "from": {"id": _JANE, "is_bot": False, "first_name": "Jane"},
                "date": 0,
                "new_chat_member": {"status": "kicked", "user": {"id": 1, "is_bot": True, "first_name": "Bot"}},
            }
        }

        with when("Jane blocks the bot"):
            _receive(context, blocked)

        with then("her link ends and nothing is sent to her"):
            assert_that(_active_links(context), equal_to([]))
            assert_that(len(context.bot.sent), equal_to(sent_before))


def test_group_messages_get_no_reply() -> None:
    with given(_GIVEN) as context:
        group = {"id": -100123, "type": "supergroup", "title": "Team"}

        with when("someone writes in a group the bot is in"):
            update_id = _receive(
                context,
                {
                    "message": {
                        "message_id": 1,
                        "from": {"id": _JANE, "is_bot": False, "first_name": "Jane"},
                        "chat": group,
                    }
                },
            )

        with then("the bot says nothing and the message is not kept"):
            assert_that(context.bot.sent, equal_to([]))
            assert_that(
                _stored(context, update_id),
                has_properties(status=AgentBarnTelegramUpdateStatus.HANDLED, payload=none()),
            )


def test_a_reply_that_cannot_be_sent_does_not_block_later_updates() -> None:
    with given(_GIVEN) as context:
        context.injector.get(AgentBarnTelegramUpdateProcessor).bot = RecordingBot(fail=True)
        _issue(context, context.sales, "token-sales")

        with when("Telegram rejects the greeting"):
            update_id = _receive(context, _private("/start token-sales"))

        with then("the link still stands and the update is settled"):
            assert_that([link.agent_id for link in _active_links(context)], contains_exactly(context.sales.agent_id))
            assert_that(_stored(context, update_id).status, is_(AgentBarnTelegramUpdateStatus.HANDLED))
